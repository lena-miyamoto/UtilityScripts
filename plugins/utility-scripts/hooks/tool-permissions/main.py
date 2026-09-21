"""tool-permissions PreToolUse hook (Python + rable).

Enforces regex allow/ask/deny policy on every tool call. Replaces the legacy
TypeScript hook's hand-rolled shell lexer with rable 0.2.1 (a Rust bash-5.3
parser). Policy semantics are preserved; only the shell-splitting layer changed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional

from rable import MatchedPairError, ParseError, parse


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Command-name wrappers stripped by normalize_words.  `time` is a rable *node*
# (handled by the walker), not a wrapper word.
# Transparent wrappers: safe to strip because they merely exec the inner command
# as-is (`command foo` runs `foo`). `eval` is deliberately absent — it re-parses
# its argument string as shell code, so its inner commands are invisible to the
# parser and stripping would let `eval "echo; ssh"` match `^echo` and pass `ssh`.
COMMAND_WRAPPERS = {"command", "exec", "builtin", "nohup"}

# Assignment-modifier keywords stripped before substitution-recursion detection.
ASSIGNMENT_MODIFIERS = {"local", "export", "declare", "typeset", "readonly"}

# `timeout` options that take a separate value word (dropped before matching).
TIMEOUT_VALUE_FLAGS = {"-s", "--signal", "-k", "--kill-after"}

# `env` options that take a separate value word (dropped before delegating).
# Long forms also work with `=` (e.g. `--unset=FOO`), handled as embedded-value
# tokens rather than consuming a separate value word.
# NOTE: `-S`/`--split-string` and `-C`/`--chdir` are deliberately absent — they
# change the inner command's meaning (merge words / change cwd), so the parser
# can't recover it; `_strip_env` bails on them instead (see below).
ENV_VALUE_FLAGS = {
    "-u", "--unset",
    "-a", "--argv0",
}

# `xargs` options whose separate value word must be dropped before delegating.
XARGS_VALUE_FLAGS = {"-I", "-n", "-P", "-L", "-l", "-d", "-a", "-E", "-s"}
XARGS_LONG_VALUE_FLAGS = {
    "--delimiter",
    "--replace",
    "--max-lines",
    "--max-args",
    "--max-procs",
    "--eof",
    "--arg-file",
    "--max-chars",
    "--process-slot-var",
}
# xargs-fed stdin consumers that are allowed to read the synthetic placeholder.
XARGS_STDIN_ARG_COMMANDS = {"rg", "grep", "ag", "fgrep", "egrep"}

SAFE_SED_SHORT_FLAGS = frozenset("nErszu")
SAFE_SED_LONG_FLAGS = frozenset(
    {
        "--quiet",
        "--silent",
        "--regexp-extended",
        "--separate",
        "--null-data",
        "--unbuffered",
        "--posix",
    }
)

# Commands eligible for the project-relative file-op fallback.
PROJECT_FILE_OP_COMMANDS = {"cp", "rm", "rmdir", "mv"}
EQUALS_FORM_VALUE_PREFIXES: dict[str, tuple[str, ...]] = {
    "cp": ("--target-directory=",),
    "mv": ("--target-directory=",),
}
SHORT_VALUE_FLAG_CHARS: dict[str, str] = {"cp": "t", "mv": "t"}

MUTATING_FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}

# Redirect targets that are never treated as write-op escapes.
SAFE_REDIRECT_PREFIXES = ("/dev/null", "/tmp/", os.path.expanduser("~/.claude/tmp/"))

# Redirect ops that write to (or clobber) a file.
WRITE_REDIRECT_OPS = (">", ">>", ">|", "&>", "&>>")

# Redirect ops whose target is not a file path (heredoc delimiter / here-string
# content), so they are excluded from path-argument checking.
NON_PATH_REDIRECT_OPS = ("<<", "<<-", "<<<")

# Files that editing is never auto-allowed, regardless of allow-rules. Matches
# both the manual `~/.claude/hooks/…` deployment and the plugin-installed copy
# under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/…`.
PROTECTED_FILE_RE = re.compile(
    r"\.claude/(permissions(\.local)?\.json|settings(\.local)?\.json|"
    r"(?:plugins/cache/[^/]+/[^/]+/[^/]+/)?hooks/tool-permissions/"
    r"(main\.py|pyproject\.toml|uv\.lock|permissions\.schema\.json))(?![\w.])",
    re.ASCII,
)

# Sentinels used to represent the empty command / synthetic xargs stdin.
EMPTY_CMD = "(empty)"
XARGS_STDIN = "__xargs_input__"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Sym:
    """A Lisp symbol in a parsed s-expression."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sym):
            return other.name == self.name
        if isinstance(other, str):
            return other == self.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class Decision:
    """A single tool-call decision: allow / ask / deny (+ optional context)."""

    decision: str  # 'allow' | 'ask' | 'deny'
    pattern: Optional[str] = None  # matched deny pattern (deny only)
    cmds: Optional[list[str]] = None  # sub-commands/paths to render


class UnparseableCommand(Exception):
    """Bash source that rable cannot parse (→ fail closed to ask)."""


# ---------------------------------------------------------------------------
# s-expression reader
# ---------------------------------------------------------------------------
#
# rable emits two string conventions in its s-expression text:
#   * word strings use backslash escapes (`\"`, `\\`, `\n`, `\t`);
#   * redirect-target and cond-term strings are written verbatim (no escaping),
#     so they may contain raw `"`, spaces, and newlines (heredoc bodies).


def read_sexp(text: str) -> Any:
    """Parse rable's s-expression text into nested lists / Sym / str / int.

    rable (like Parable) emits two string conventions:
      * word strings use backslash escapes (`\"`, `\\`, `\n`, `\t`) — no raw `"`;
      * redirect-target and cond-term strings are written **verbatim** (no
        escaping), so they may contain raw `"`, spaces, and newlines (heredoc
        bodies). Those strings are always the last child of their node and are
        immediately followed by `)`, so their closing quote is the `"` directly
        preceding that `)`.
    """
    n = len(text)
    pos = 0

    def skip_ws() -> None:
        nonlocal pos
        while pos < n and text[pos] in " \t\n\r":
            pos += 1

    def read_escaped() -> str:
        nonlocal pos
        pos += 1  # opening quote
        out: list[str] = []
        while pos < n:
            c = text[pos]
            if c == "\\":
                pos += 1
                if pos < n:
                    nxt = text[pos]
                    # rable's word strings escape newline/tab as \n / \t; everything
                    # else (\\, \") drops the escaping backslash.
                    if nxt == "n":
                        out.append("\n")
                    elif nxt == "t":
                        out.append("\t")
                    else:
                        out.append(nxt)
                pos += 1
            elif c == '"':
                pos += 1
                break
            else:
                out.append(c)
                pos += 1
        return "".join(out)

    def read_verbatim() -> str:
        nonlocal pos
        pos += 1  # opening quote
        out: list[str] = []
        while pos < n:
            c = text[pos]
            if c == '"' and (pos + 1 >= n or text[pos + 1] == ")"):
                pos += 1
                break
            out.append(c)
            pos += 1
        return "".join(out)

    def read_atom(parent_head: str, index: int) -> Any:
        nonlocal pos
        skip_ws()
        c = text[pos]
        if c == "(":
            return read_list()
        if c == '"':
            verbatim = (parent_head == "redirect" and index == 2) or (
                parent_head == "cond-term" and index == 1
            )
            return read_verbatim() if verbatim else read_escaped()
        # bare token (symbol, int)
        j = pos
        while j < n and text[j] not in " \t\n\r()":
            j += 1
        tok = text[pos:j]
        pos = j
        if tok == "nil":
            return Sym("nil")
        if re.fullmatch(r"-?\d+", tok):
            return int(tok)
        return Sym(tok)

    def read_list() -> list:
        nonlocal pos
        pos += 1  # '('
        skip_ws()
        if pos < n and text[pos] == ")":
            pos += 1
            return []
        head_start = pos
        while pos < n and text[pos] not in " \t\n\r()":
            pos += 1
        head = text[head_start:pos]
        items: list[Any] = [Sym(head)]
        index = 1
        while True:
            skip_ws()
            if pos >= n or text[pos] == ")":
                pos += 1
                break
            items.append(read_atom(head, index))
            index += 1
        return items

    skip_ws()
    results: list[Any] = []
    while pos < n:
        results.append(read_atom("", 0))
        skip_ws()
    return results[0] if len(results) == 1 else results


# ---------------------------------------------------------------------------
# Bash parsing
# ---------------------------------------------------------------------------


def parse_command(source: str) -> list[Any]:
    """Parse Bash source into a list of sexp ASTs. Raises UnparseableCommand."""
    try:
        nodes = parse(source)
    except (ParseError, MatchedPairError):
        raise UnparseableCommand()
    result: list[Any] = []
    for node in nodes:
        ast = read_sexp(node.to_sexp())
        # A conditional with redirects emits two top-level sexps (cond + redirect).
        if isinstance(ast, list) and ast and isinstance(ast[0], list):
            result.extend(ast)
        else:
            result.append(ast)
    return result


# ---------------------------------------------------------------------------
# Structure helpers
# ---------------------------------------------------------------------------


def _split_command(node: list[Any]) -> tuple[list[str], list[tuple[str, str]]]:
    """Split a command node into (words, redirects)."""
    words: list[str] = []
    redirects: list[tuple[str, str]] = []
    for child in node[1:]:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == "word":
            words.append(child[1] if len(child) > 1 else "")
        elif child[0] == "redirect":
            op = child[1]
            target = child[2]
            if isinstance(target, int):
                target = str(target)
            redirects.append((op, target))
    return words, redirects


def _cmd_name(words: list[str]) -> str:
    if not words:
        return ""
    return words[0].rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Text-level unsafe-construct scan
# ---------------------------------------------------------------------------


def _is_command_substitution(s: str, i: int) -> bool:
    """True if s[i:i+2] starts a command substitution ($( or `)."""
    if s[i] == "$" and i + 1 < len(s) and s[i + 1] == "(":
        # not $(( arithmetic
        return not (i + 2 < len(s) and s[i + 2] == "(")
    return False


def _unsafe_text(s: str) -> bool:
    """Scan a single token string for shell-expansion hazards.

    Mirrors the legacy hook's whole-string scan: flags command substitution,
    backticks, `${x@P}` indirect expansion, and process substitution — but NOT
    `$((…))` arithmetic and NOT anything inside single quotes.
    """
    n = len(s)
    i = 0
    in_single = False
    in_double = False
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            if in_single:
                in_single = False
            elif not in_double:
                in_single = True
            i += 1
            continue
        if c == '"':
            if not in_single:
                in_double = not in_double
            i += 1
            continue
        if in_single:
            i += 1
            continue
        if c == "`":
            return True
        if c == "$":
            if _is_command_substitution(s, i):
                return True
        if c == "@":
            # ${x@P} prompt-string expansion (indirect/eval-like): caught at the
            # closing `@P}` sequence so any parameter-name length matches.
            if i + 2 < n and s[i + 1] == "P" and s[i + 2] == "}":
                return True
        if c in "<>":
            # process substitution <( ... ) / >( ... )
            if i + 1 < n and s[i + 1] == "(":
                return True
        i += 1
    return False


def _unsafe_redirect(op: str, target: str) -> bool:
    """True if a redirect op/target is a write-op escape."""
    if isinstance(target, int):
        return False  # fd dup/close, never a file write
    if op in WRITE_REDIRECT_OPS:
        if target.startswith(SAFE_REDIRECT_PREFIXES):
            return False
        return True
    if op == ">&":
        # numeric fd-dup (>&1, >&-) is safe; string target is a write.
        if target.isdigit() or target == "-":
            return False
        if target.startswith(SAFE_REDIRECT_PREFIXES):
            return False
        return True
    return False


def unsafe_construct(words: list[str], redirects: list[tuple[str, str]]) -> bool:
    """Structural allow guard: reject command substitution / procsub / writes."""
    for w in words:
        if _unsafe_text(w):
            return True
    for op, target in redirects:
        if _unsafe_redirect(op, target):
            return True
        # heredoc bodies and here-string content are still expanded by bash.
        if op in ("<<", "<<-", "<<<") and _unsafe_text(target):
            return True
    return False


# ---------------------------------------------------------------------------
# Word normalization
# ---------------------------------------------------------------------------


def unquote_word(word: str) -> str:
    """Drop quote chars and unescape backslashes (legacy `unquoteWord`)."""
    out: list[str] = []
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        if ch == "\\":
            if i + 1 < n:
                out.append(word[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch == "'" or ch == '"':
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_cr(word: str) -> str:
    return word[:-1] if word.endswith("\r") else word


def _strip_timeout(words: list[str]) -> list[str]:
    """Strip `timeout`'s flags + the mandatory DURATION; return the inner words.

    `timeout` runs an arbitrary command, so without this it'd be a blanket wrapper
    around every deny rule (`timeout 1 rm -rf ~`).
    """
    toks = words[1:]
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w.startswith("-"):
            i += 1
            if w in TIMEOUT_VALUE_FLAGS and i < n:
                i += 1  # consume the flag's value token
            continue
        # first non-flag token is DURATION; the rest is the command
        return toks[i + 1 :]
    return []


def _strip_env(words: list[str]) -> list[str] | None:
    """Strip `env`'s options + `NAME=value` assignments; return the inner command.

    `env [OPTION]... [NAME=VALUE]... [COMMAND [ARG]...]` runs an arbitrary
    command, so — like `timeout` — it'd otherwise be a blanket wrapper around
    every deny rule (`env FOO=1 rm -rf ~`). Options (including value-flags and
    their value token, plus the `--`/`-` terminator) and leading assignments are
    dropped; the remaining words are the inner command. Bare `env` returns `[]`.

    Returns `None` when the inner command can't be determined safely:
    - `-S` / `--split-string` split their value into words that are *merged*
      with the trailing args (e.g. `env -S 'ssh' host x` runs `ssh host x`).
    - `-C` / `--chdir` change the cwd, so every relative path in the inner
      command resolves inside it (`env -C ~/.ssh cat id_rsa` reads the key).
    The caller must fail closed.
    """
    toks = words[1:]
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--" or w == "-":
            i += 1  # end of options; assignments may still follow
            break
        if not w.startswith("-"):
            break
        # `-S`/`--split-string` merge words; `-C`/`--chdir` rebase relative paths.
        # Both make the inner command opaque — refuse to delegate. The glued
        # short forms (`-C/home/...`, `-Sssh`) are accepted by getopt and are
        # every bit as opaque as the spaced/`=` forms, so cover those too.
        if w.startswith(("-S", "-C", "--split-string", "--chdir")):
            return None
        i += 1
        if "=" not in w and w in ENV_VALUE_FLAGS and i < n:
            i += 1  # consume the flag's value token
    while i < n and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i]):
        i += 1
    return toks[i:]


def normalize_words(words: list[str]) -> list[str]:
    """Normalize a command's words for matching.

    Strips leading assignment words (`X=1`), the `timeout` and `env` wrappers,
    and command wrappers (`command`/`exec`/`builtin`/`nohup`), unquotes
    the command word, and strips one trailing CR per word.
    """
    w = [_strip_cr(x) for x in words]
    i = 0
    while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
        i += 1
    w = w[i:]
    while w:
        # Resolve to the basename so `/usr/bin/env`, `/bin/nohup`, … are stripped
        # the same as their bare names (matches `_cmd_name` for sed/awk/xargs).
        cmd = unquote_word(w[0]).rsplit("/", 1)[-1]
        if cmd in COMMAND_WRAPPERS:
            rest = w[1:]
            if cmd == "command":
                next_word = rest[0] if rest else ""
                # command -v/-V (or bare): introspection, not execution — keep as-is
                if next_word in ("", "-v", "-V"):
                    break
                # command -p/-P: runs NAME with a default PATH — strip the flag
                if next_word in ("-p", "-P"):
                    rest = rest[1:]
            w = rest
            continue
        if cmd == "timeout":
            w = _strip_timeout(w)
            continue
        if cmd == "env":
            stripped = _strip_env(w)
            if stripped is None:
                break  # `-S`/`-C` make the inner command opaque — fail closed
            w = stripped
            continue
        break
    if not w:
        return []
    return [unquote_word(w[0])] + w[1:]


def _is_bare_function_call(words: list[str], declared: set[str]) -> bool:
    """True if `words` is a bare invocation of a declared function.

    Matches only the direct `name …` (or `X=1 name …`) form, after stripping
    leading assignment words. Wrappers (`command`/`exec`/`builtin`/`nohup`/
    `timeout`/`env`) do NOT count: they run an external command or change
    execution semantics, so the inner name must still go through policy matching
    rather than being auto-allowed as a function call.
    """
    if not declared or not words:
        return False
    w = [_strip_cr(x) for x in words]
    i = 0
    while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
        i += 1
    if i >= len(w):
        return False
    return unquote_word(w[i]).rsplit("/", 1)[-1] in declared


def render_match_string(words: list[str], redirects: list[tuple[str, str]]) -> str:
    """Canonical single-space match string, redirects appended."""
    parts = list(words)
    for op, target in redirects:
        parts.append(f"{op} {target}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Assignment-substitution recursion
# ---------------------------------------------------------------------------


def _extract_subst_body(rhs: str) -> Optional[str]:
    """Return the body of a single leading `$(…)`, or None if `rhs` isn't exactly one."""
    if not rhs.startswith("$("):
        return None
    depth = 0
    in_single = False
    in_double = False
    i = 0
    n = len(rhs)
    while i < n:
        c = rhs[i]
        if c == "\\" and not in_single:
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    if i != n - 1:
                        return None  # trailing material after the substitution
                    return rhs[2:i]
        i += 1
    return None


def _is_assignment_only(words: list[str]) -> bool:
    """True if `words` is a pure assignment command with no command name.

    Matches `ids="$1"`, `X=1`, and `export X=1` / `local -a X=1` (an optional
    assignment-modifier keyword plus short flags, then only `NAME=…` words).
    Returns False for a bare modifier (`export` alone — prints the environment,
    like `env`) and for any real command name (`env`, `timeout`, `rm`).
    """
    toks = [_strip_cr(x) for x in words]
    if not toks:
        return False
    if toks[0] in ASSIGNMENT_MODIFIERS:
        toks = toks[1:]
        while toks and re.fullmatch(r"-[a-zA-Z]+", toks[0]):
            toks = toks[1:]
    return bool(toks) and all(
        re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) for w in toks
    )


def extract_assignment_substitutions(words: list[str]) -> Optional[str]:
    """Return the `$(…)` bodies of pure assignment words, or None if not applicable.

    Strips an optional modifier keyword (`local`/`export`/`declare`/`typeset`/`readonly`)
    plus any short flags, then requires every remaining word to be `NAME=$(…)` with a
    single balanced-paren substitution. Bodies are joined with `; ` for re-parsing.
    """
    toks = list(words)
    if toks and toks[0] in ASSIGNMENT_MODIFIERS:
        toks = toks[1:]
        while toks and re.fullmatch(r"-[a-zA-Z]+", toks[0]):
            toks = toks[1:]
    if not toks:
        return None
    bodies: list[str] = []
    for w in toks:
        m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)
        if not m:
            return None
        body = _extract_subst_body(w[m.end() :])
        if body is None:
            return None
        bodies.append(body)
    return "; ".join(bodies)


# ---------------------------------------------------------------------------
# xargs delegation
# ---------------------------------------------------------------------------


def extract_xargs_inner(norm: list[str]) -> Optional[list[str]]:
    """Extract the delegated inner command from a normalized xargs invocation.

    Returns None for bare `xargs` (no inner command), leaving the whole command
    to normal matching. Long value-flags without `=` (`--max-args 4`) consume
    their value token (quirk fix, unlike the legacy hook).
    """
    toks = norm[1:]
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "":
            return None
        if not w.startswith("-"):
            inner = toks[i:]
            if len(inner) == 1 and _cmd_name(inner) in XARGS_STDIN_ARG_COMMANDS:
                return inner + [XARGS_STDIN]
            return inner
        i += 1
        if "=" in w:
            continue  # value embedded in the flag token (e.g. --max-args=4)
        if w in XARGS_VALUE_FLAGS or w in XARGS_LONG_VALUE_FLAGS:
            i += 1  # consume the flag's value token
    return None


def extract_xargs_arg_file(norm: list[str]) -> Optional[str]:
    """Return the `-a FILE` / `--arg-file FILE` / `--arg-file=FILE` path, else None.

    `xargs -a FILE` reads items from FILE (not stdin). That read is invisible to
    the inner-command delegation (which drops `-a`'s value), so the path must be
    surfaced for the read-path protection separately.
    """
    toks = norm[1:]
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--":
            break
        if w == "-a" or w == "--arg-file":
            return toks[i + 1] if i + 1 < n else None
        if w.startswith("--arg-file="):
            return w[len("--arg-file=") :]
        if w.startswith("-"):
            i += 1
            if "=" not in w and (w in XARGS_VALUE_FLAGS or w in XARGS_LONG_VALUE_FLAGS):
                i += 1  # consume the flag's value token (e.g. `-n 4` before `-a`)
            continue
        break
    return None


# ---------------------------------------------------------------------------
# WebFetch URL delegation for wget/curl
# ---------------------------------------------------------------------------
#
# A Bash `wget`/`curl` that is a plain GET of a URL the policy already allows
# for `WebFetch` is auto-allowed, overriding the blanket `^(curl|wget)\s` ask
# rule. The delegation is fail-closed: it only fires for a provably plain fetch
# (no request body/upload, no method override, no config/netrc/input-file, no
# recursive/mirror/host-spanning wget), and file output (`-O`/`-o`) is routed
# through the normal deny/protected-path checks.

_WEB_FETCH_URL_RE = re.compile(r"^https?://")

# Flags that make the command *not* a plain fetch (rejected -> fall through).
_CURL_REJECT_LONG = {
    "--data", "--data-ascii", "--data-binary", "--data-raw",
    "--data-urlencode", "--json", "--form", "--form-string",
    "--upload-file", "--config", "--netrc", "--netrc-file",
    "--remote-name", "--remote-header-name",
}
_CURL_REJECT_SHORT = set("dFTKOnJ")
_WGET_REJECT_LONG = {
    "--post-data", "--post-file", "--body-data", "--body-file",
    "--method", "--input-file", "--config", "--execute",
    "--recursive", "--mirror", "--page-requisites", "--span-hosts",
    "--domains", "--exclude-domains", "--follow-ftp",
}
_WGET_REJECT_SHORT = set("rmpkKEHei")

# Output flags: the target is a file/dir write -> route through path protection.
_CURL_OUTPUT_LONG = {"--output", "--output-dir"}
_CURL_OUTPUT_SHORT = "o"
_WGET_OUTPUT_LONG = {"--output-document", "--directory-prefix"}
_WGET_OUTPUT_SHORT = "OP"

# curl's `-X`/`--request` is accepted only for GET/HEAD.
_CURL_METHOD_LONG = {"--request"}
_CURL_METHOD_SHORT = "X"

# Harmless value-taking flags: their value token is consumed so it is never
# mistaken for a URL. Not exhaustive — a missed value flag merely yields an
# over-strict ask (its value token is a non-URL positional -> fail closed).
_CURL_VALUE_LONG = {
    "--header", "--user-agent", "--referer", "--user", "--max-time",
    "--cookie", "--cookie-jar", "--range", "--time-cond", "--write-out",
    "--cert", "--key", "--proxy", "--proxy-user", "--connect-timeout",
}
_CURL_VALUE_SHORT = set("HAeumbcrzw")
_WGET_VALUE_LONG = {
    "--user-agent", "--timeout", "--output-file", "--quota", "--accept",
    "--reject", "--base", "--wait", "--level", "--tries",
}
_WGET_VALUE_SHORT = set("oUTQARBlw")


def _analyze_web_fetch(norm: list[str]) -> Optional[tuple[list[str], list[str]]]:
    """Classify a normalized wget/curl as a plain fetch -> (urls, output_paths).

    Returns None (fail closed -> caller falls through to normal matching) when
    the command is not a provably plain fetch of one or more URLs.
    """
    name = _cmd_name(norm)
    if name not in ("wget", "curl"):
        return None
    curl = name == "curl"
    reject_long = _CURL_REJECT_LONG if curl else _WGET_REJECT_LONG
    reject_short = _CURL_REJECT_SHORT if curl else _WGET_REJECT_SHORT
    output_long = _CURL_OUTPUT_LONG if curl else _WGET_OUTPUT_LONG
    output_short = _CURL_OUTPUT_SHORT if curl else _WGET_OUTPUT_SHORT
    value_long = _CURL_VALUE_LONG if curl else _WGET_VALUE_LONG
    value_short = _CURL_VALUE_SHORT if curl else _WGET_VALUE_SHORT
    method_long = _CURL_METHOD_LONG if curl else set()
    method_short = _CURL_METHOD_SHORT if curl else ""

    urls: list[str] = []
    output_paths: list[str] = []
    toks = norm[1:]
    i = 0
    n = len(toks)
    while i < n:
        w = unquote_word(toks[i])
        if w == "--":
            i += 1
            continue
        if w.startswith("--"):
            flag, eq, val = w.partition("=")
            if flag in reject_long:
                return None
            if flag in method_long:
                method = val if eq else (toks[i + 1] if i + 1 < n else "")
                if method not in ("GET", "HEAD"):
                    return None
                i += 1 if eq else 2
                continue
            if flag in output_long:
                target = val if eq else (toks[i + 1] if i + 1 < n else None)
                if target is None:
                    return None
                if target != "-":
                    output_paths.append(target)
                i += 1 if eq else 2
                continue
            if curl and flag == "--url":
                target = val if eq else (toks[i + 1] if i + 1 < n else None)
                if target is None:
                    return None
                urls.append(target)
                i += 1 if eq else 2
                continue
            if flag in value_long:
                i += 1 if eq else 2
                continue
            # Unknown long flag -> fail closed.
            return None
        if w.startswith("-") and w != "-":
            body = w[1:]
            j = 0
            while j < len(body):
                c = body[j]
                rest = body[j + 1 :]
                if c in reject_short:
                    return None
                if c in method_short:
                    method = rest if rest else (toks[i + 1] if i + 1 < n else "")
                    if method not in ("GET", "HEAD"):
                        return None
                    if not rest:
                        i += 1
                    break
                if c in output_short:
                    target = rest if rest else (toks[i + 1] if i + 1 < n else None)
                    if target is None:
                        return None
                    if target != "-":
                        output_paths.append(target)
                    if not rest:
                        i += 1
                    break
                if c in value_short:
                    if not rest:
                        i += 1
                    break
                j += 1
            i += 1
            continue
        if _WEB_FETCH_URL_RE.match(w):
            urls.append(w)
        else:
            return None
        i += 1
    return (urls, output_paths) if urls else None


def evaluate_web_fetch(norm: list[str], sources: list[dict]) -> Optional[Decision]:
    """Auto-allow a plain wget/curl fetch of WebFetch-allowed URLs.

    Returns a Decision to override the blanket wget/curl ask, or None to fall
    through to normal Bash matching. A WebFetch deny on any URL wins, as do the
    deny/ask rules on any `-O`/`-o` output path.
    """
    analysis = _analyze_web_fetch(norm)
    if analysis is None:
        return None
    urls, output_paths = analysis
    for u in urls:
        op = prioritized_opinion(sources, "WebFetch", u)
        if op is None or op.decision == "ask":
            return None  # off-list / explicit ask -> fall through
        if op.decision == "deny":
            return Decision("deny", op.pattern, [u])
    for p in output_paths:
        abs_p = os.path.abspath(expand_tilde_in_arg(p))
        op = read_rule_opinion_for_paths(sources, [abs_p])
        if op is not None:
            return Decision(op.decision, op.pattern, [p])
    return Decision("allow")


# ---------------------------------------------------------------------------
# sed safety (direct port of the TS state machine)
# ---------------------------------------------------------------------------


def is_safe_sed_flag(token: str) -> bool:
    if token in SAFE_SED_LONG_FLAGS:
        return True
    if token.startswith("--"):
        return False
    if len(token) < 2:
        return False
    return all(c in SAFE_SED_SHORT_FLAGS for c in token[1:])


def parse_optional_address(s: str, i: int) -> int:
    n = len(s)
    if i >= n:
        return i
    c = s[i]
    if c == "$":
        return i + 1
    if "0" <= c <= "9":
        j = i
        while j < n and "0" <= s[j] <= "9":
            j += 1
        if j < n and s[j] == "~":
            j += 1
            while j < n and "0" <= s[j] <= "9":
                j += 1
        return j
    if c == "/":
        j = i + 1
        while j < n:
            if s[j] == "\\":
                j += 2
            elif s[j] == "/":
                return j + 1
            else:
                j += 1
        return -1
    return i


def skip_addresses(s: str, i: int) -> int:
    n = len(s)
    i = parse_optional_address(s, i)
    if i < 0:
        return -1
    if i < n and s[i] == ",":
        i = parse_optional_address(s, i + 1)
        if i < 0:
            return -1
    while i < n and (s[i] == " " or s[i] == "\t"):
        i += 1
    if i < n and s[i] == "!":
        i += 1
        while i < n and (s[i] == " " or s[i] == "\t"):
            i += 1
    return i


def is_safe_subst_flag_char(c: str) -> bool:
    return c in "gpIiMm" or "0" <= c <= "9"


def scan_substitution(s: str, i: int) -> int:
    n = len(s)
    if i + 1 >= n:
        return -1
    delim = s[i + 1]
    if delim == "\\" or delim == "\n" or delim == " ":
        return -1

    def scan_to_delim(k: int) -> int:
        while k < n:
            if s[k] == "\\":
                k += 2
            elif s[k] == delim:
                return k
            else:
                k += 1
        return -1

    after_pattern = scan_to_delim(i + 2)
    if after_pattern < 0:
        return -1
    after_replacement = scan_to_delim(after_pattern + 1)
    if after_replacement < 0:
        return -1
    k = after_replacement + 1
    while k < n:
        f = s[k]
        if f == "e" or f == "w" or f == "W":
            return -1
        if not is_safe_subst_flag_char(f):
            break
        k += 1
    return k


def is_safe_sed_script(script: str) -> bool:
    n = len(script)
    i = 0
    while i < n:
        while i < n and script[i] in " \t;\n":
            i += 1
        if i >= n:
            break
        i = skip_addresses(script, i)
        if i < 0:
            return False
        cmd = script[i]
        if cmd == "s":
            i = scan_substitution(script, i)
            if i < 0:
                return False
        elif cmd in "pPdD=":
            i += 1
        else:
            return False
    return True


def sed_expression_script(word: str, words: list[str], i: int) -> Optional[tuple[str, int]]:
    if word in ("-e", "--expression"):
        if i + 1 >= len(words):
            return None
        return unquote_word(words[i + 1]), i + 2
    if word.startswith("--expression="):
        return unquote_word(word[len("--expression=") :]), i + 1
    return None


def is_safe_sed(words: list[str]) -> bool:
    toks = words[1:]
    script_seen = False
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--":
            break
        expr = sed_expression_script(w, toks, i)
        if expr is not None:
            script, nxt = expr
            if not is_safe_sed_script(script):
                return False
            script_seen = True
            i = nxt
            continue
        if w.startswith("-"):
            if not is_safe_sed_flag(w):
                return False
            i += 1
            continue
        if not script_seen:
            if not is_safe_sed_script(unquote_word(w)):
                return False
            script_seen = True
        i += 1
    return script_seen


def is_safe_sed_stdin_only(words: list[str]) -> bool:
    toks = words[1:]
    script_seen = False
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--":
            return False
        expr = sed_expression_script(w, toks, i)
        if expr is not None:
            script, nxt = expr
            if not is_safe_sed_script(script):
                return False
            script_seen = True
            i = nxt
            continue
        if w.startswith("-"):
            if not is_safe_sed_flag(w):
                return False
            i += 1
            continue
        if not script_seen:
            if not is_safe_sed_script(unquote_word(w)):
                return False
            script_seen = True
        else:
            return False
        i += 1
    return script_seen


def is_sed_in_place_flag(token: str) -> bool:
    if token == "--in-place" or token.startswith("--in-place="):
        return True
    if token.startswith("-i"):
        return True
    if (
        token.startswith("-")
        and not token.startswith("--")
        and token.endswith("i")
        and len(token) >= 2
    ):
        return all(c in SAFE_SED_SHORT_FLAGS for c in token[1:-1])
    return False


def is_safe_sed_in_place(words: list[str], sources: list[dict]) -> bool:
    toks = words[1:]
    script_seen = False
    in_place_seen = False
    file_paths: list[str] = []
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--":
            break
        expr = sed_expression_script(w, toks, i)
        if expr is not None:
            script, nxt = expr
            if not is_safe_sed_script(script):
                return False
            script_seen = True
            i = nxt
            continue
        if w.startswith("-"):
            if is_sed_in_place_flag(w):
                in_place_seen = True
            elif not is_safe_sed_flag(w):
                return False
            i += 1
            continue
        if not script_seen:
            if not is_safe_sed_script(unquote_word(w)):
                return False
            script_seen = True
        else:
            file_paths.append(expand_tilde_in_arg(unquote_word(w)))
        i += 1
    if not in_place_seen or not script_seen or not file_paths:
        return False
    for fp in file_paths:
        abs_p = os.path.abspath(fp)
        op = prioritized_opinion(sources, "Edit", abs_p)
        if op is not None and op.decision != "allow":
            return False
    return True


# ---------------------------------------------------------------------------
# awk safety (fail-closed scanner)
# ---------------------------------------------------------------------------


_AWK_DANGEROUS_IDENTIFIERS = frozenset({"system", "SYMTAB", "FUNCTAB", "dbmopen"})


def _awk_ident_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _is_single_quoted_awk_program(word: str) -> bool:
    """True if the token is one fully single-quoted shell word.

    A single ``'...'`` pair wrapping the whole token means the program text
    reaches awk literally, with no shell interpolation. Concat-quoted tokens
    (``'a'"x"``, ``'a'$x'b'``), double-quoted (``"prog"``), unquoted (``prog``),
    and escaped-quote (``\\'prog\\'``) forms all fail here. A ``"`` or backtick
    *inside* the quotes is literal awk, so it is not rejected.
    """
    return (
        len(word) >= 2
        and word[0] == "'"
        and word[-1] == "'"
        and word.count("'") == 2
    )


def is_safe_awk_program(prog: str) -> bool:
    """Fail-closed scanner: True only if the awk program is provably safe."""
    n = len(prog)
    i = 0
    depth = 0
    brace_depth = 0
    head: Optional[str] = None  # "print"/"printf" while in that statement head
    prev_operand = False
    getline_state = 0  # 0 none, 1 saw `getline`, 2 saw `getline` + lvalue
    while i < n:
        c = prog[i]
        if c == "#":
            while i < n and prog[i] != "\n":
                i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            head = None
            getline_state = 0
            prev_operand = False
            i += 1
            continue
        if c == "\\":
            if i + 1 < n and prog[i + 1] == "\n":
                i += 2  # line continuation: head state persists
                continue
            return False
        if c == '"':
            j = i + 1
            while j < n:
                if prog[j] == "\\":
                    j += 2
                elif prog[j] == '"':
                    break
                else:
                    j += 1
            if j >= n:
                return False
            if "/inet" in prog[i + 1 : j]:
                return False
            i = j + 1
            prev_operand = True
            getline_state = 0
            continue
        if c == "/":
            if prev_operand:
                i += 2 if i + 1 < n and prog[i + 1] == "=" else 1
                prev_operand = False
                continue
            if i + 1 < n and prog[i + 1] == "=":
                return False
            if i + 1 < n and prog[i + 1] == "/":
                i += 2  # empty regex //
                prev_operand = True
                continue
            j = i + 1
            while j < n:
                if prog[j] == "\\":
                    j += 2
                elif prog[j] == "/":
                    break
                else:
                    j += 1
            if j >= n:
                return False
            i = j + 1
            prev_operand = True
            continue
        if c == "(":
            depth += 1
            prev_operand = False
            i += 1
            continue
        if c == ")":
            depth -= 1
            if depth < 0:
                return False
            prev_operand = True
            i += 1
            continue
        if c == "[":
            prev_operand = False
            i += 1
            continue
        if c == "]":
            prev_operand = True
            i += 1
            continue
        if c == "{":
            brace_depth += 1
            head = None
            getline_state = 0
            prev_operand = False
            i += 1
            continue
        if c == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return False
            head = None
            getline_state = 0
            prev_operand = False
            i += 1
            continue
        if c == ";":
            head = None
            getline_state = 0
            prev_operand = False
            i += 1
            continue
        if c in ",?:":
            prev_operand = False
            i += 1
            continue
        if c == ">":
            if i + 1 < n and prog[i + 1] == "=":
                i += 2  # >= comparison
                prev_operand = False
                continue
            if i + 1 < n and prog[i + 1] == ">":
                return False  # >> append redirect
            if depth == 0 and head in ("print", "printf"):
                return False  # print/printf output redirect
            i += 1
            prev_operand = False
            continue
        if c == "<":
            if getline_state != 0:
                if i + 1 < n and prog[i + 1] == "=":
                    i += 2  # <= comparison
                    getline_state = 0
                    prev_operand = False
                    continue
                return False  # getline input redirect
            i += 2 if i + 1 < n and prog[i + 1] == "=" else 1
            prev_operand = False
            continue
        if c == "|":
            if i + 1 < n and prog[i + 1] == "&":
                return False  # |& coprocess
            if i + 1 < n and prog[i + 1] == "|":
                i += 2  # || logical or
                prev_operand = False
                continue
            return False  # pipe
        if c == "&":
            if i + 1 < n and prog[i + 1] == "&":
                i += 2  # && logical and
                prev_operand = False
                continue
            return False
        if c == "=":
            i += 2 if i + 1 < n and prog[i + 1] == "=" else 1
            prev_operand = False
            continue
        if c == "!":
            if i + 1 < n and prog[i + 1] in "=~":
                i += 2
            else:
                i += 1
            prev_operand = False
            continue
        if c == "~":
            prev_operand = False
            i += 1
            continue
        if c == "@":
            return False
        if c in "+-":
            if i + 1 < n and prog[i + 1] == c:
                i += 2  # postfix/prefix ++ or -- keeps operand class
                prev_operand = True
            elif i + 1 < n and prog[i + 1] == "=":
                i += 2
                prev_operand = False
            else:
                i += 1
                prev_operand = False
            continue
        if c in "*%^":
            i += 2 if i + 1 < n and prog[i + 1] == "=" else 1
            prev_operand = False
            continue
        if c == "$":
            if i + 1 < n and prog[i + 1].isdigit():
                j = i + 1
                while j < n and prog[j].isdigit():
                    j += 1
                i = j
                prev_operand = True
                continue
            if i + 1 < n and (prog[i + 1].isalpha() or prog[i + 1] == "_"):
                j = i + 1
                while j < n and _awk_ident_char(prog[j]):
                    j += 1
                i = j
                prev_operand = True
                continue
            i += 1  # $(expr): the "(" is handled next iteration
            prev_operand = False
            continue
        if c.isdigit():
            j = i
            while j < n and (prog[j].isdigit() or prog[j] == "."):
                j += 1
            i = j
            prev_operand = True
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and _awk_ident_char(prog[j]):
                j += 1
            ident = prog[i:j]
            if ident in _AWK_DANGEROUS_IDENTIFIERS:
                return False
            if ident == "print":
                head = "print"
            elif ident == "printf":
                head = "printf"
            if ident == "getline":
                getline_state = 1
            elif getline_state == 1:
                getline_state = 2
            else:
                getline_state = 0
            i = j
            prev_operand = True
            continue
        return False
    return depth == 0 and brace_depth == 0


def is_safe_awk(words: list[str]) -> bool:
    toks = words[1:]
    program_seen = False
    i = 0
    n = len(toks)
    while i < n:
        w = toks[i]
        if w == "--":
            i += 1
            continue
        if w.startswith("-") and len(w) > 1:
            if w in ("--version", "-V", "--help"):
                return not program_seen
            if w.startswith("-F"):
                i += 2 if w == "-F" else 1
                continue
            if w.startswith("-v"):
                i += 2 if w == "-v" else 1
                continue
            if w == "-c":
                i += 1
                continue
            if w in ("-e", "--source"):
                if i + 1 >= n:
                    return False
                nxt = toks[i + 1]
                if not _is_single_quoted_awk_program(nxt):
                    return False
                if not is_safe_awk_program(nxt[1:-1]):
                    return False
                program_seen = True
                i += 2
                continue
            if w.startswith("--source="):
                src = w[len("--source=") :]
                if not _is_single_quoted_awk_program(src):
                    return False
                if not is_safe_awk_program(src[1:-1]):
                    return False
                program_seen = True
                i += 1
                continue
            return False
        if not program_seen:
            if not _is_single_quoted_awk_program(w):
                return False
            prog = w[1:-1]
            if not prog or not is_safe_awk_program(prog):
                return False
            program_seen = True
        i += 1
    return program_seen


# ---------------------------------------------------------------------------
# Path-argument checking
# ---------------------------------------------------------------------------


def expand_tilde_in_arg(arg: str) -> str:
    home = os.path.expanduser("~")
    if arg == "~":
        return home
    if arg.startswith("~/"):
        return home + arg[1:]
    return arg


def extract_path_args(words: list[str]) -> list[str]:
    """Resolve path-shaped positional words (lexical, no symlink resolution)."""
    paths: list[str] = []
    for word in words:
        arg = unquote_word(word)
        if arg.startswith("-"):
            continue
        expanded = expand_tilde_in_arg(arg)
        if (
            expanded.startswith("/")
            or expanded.startswith("~")
            or expanded.startswith("../")
            or expanded == ".."
        ):
            paths.append(os.path.abspath(expanded))
    return paths


def extract_redirect_path_args(redirects: list[tuple[str, str]]) -> list[str]:
    """File-redirect targets that are candidates for path-argument checking.

    Excludes fd dups/closes (int targets) and heredoc/here-string targets (their
    `target` is a delimiter or literal string, not a file path).
    """
    out: list[str] = []
    for op, target in redirects:
        if isinstance(target, int):
            continue
        if op in NON_PATH_REDIRECT_OPS:
            continue
        out.append(target)
    return out


def read_rule_opinion_for_paths(
    sources: list[dict], paths: list[str]
) -> Optional[Decision]:
    """Resolve each path as a Read target; deny > ask > None (first-path)."""
    if not paths:
        return None

    def read_opinion(p: str) -> Optional[Decision]:
        targets = [p] if p.endswith("/") else [p, p + "/"]
        for t in targets:
            op = prioritized_opinion(sources, "Read", t)
            if op is not None:
                return op
        return None

    for p in paths:
        op = read_opinion(p)
        if op is not None and op.decision == "deny":
            return op
    for p in paths:
        op = read_opinion(p)
        if op is not None and op.decision == "ask":
            return op
    return None


def _touches_sensitive_project_dir(abs_path: str) -> bool:
    return re.search(r"(^|/)(\.claude|\.git)(/|$)", abs_path) is not None


def _extract_bundled_short_value(word: str, flag_char: str) -> Optional[str]:
    if not word.startswith("-") or word.startswith("--"):
        return None
    body = word[1:]
    idx = body.find(flag_char)
    if idx == -1 or not re.match(r"^[a-zA-Z]*$", body[:idx]):
        return None
    value = body[idx + 1 :]
    return value if value != "" else None


def _extract_all_positional_args(
    after: list[str],
    equals_prefixes: tuple[str, ...] = (),
    short_flag_char: Optional[str] = None,
) -> tuple[list[str], Optional[int]]:
    """Extract positional operands; also return the index of the first
    target-directory value (`--target-directory=`, `-t DIR`, or a bundled
    short form), else None."""
    args: list[str] = []
    target_dir_idx: Optional[int] = None
    pending_target_dir = False
    end_of_flags = False
    for word in after:
        if not end_of_flags and word == "--":
            end_of_flags = True
            continue
        if not end_of_flags and word.startswith("-") and word != "-":
            pending_target_dir = False
            eq = next((p for p in equals_prefixes if word.startswith(p)), None)
            if eq is not None:
                target_dir_idx = len(args)
                args.append(unquote_word(word[len(eq) :]))
                continue
            if short_flag_char is not None:
                bundled = _extract_bundled_short_value(word, short_flag_char)
                if bundled is not None:
                    target_dir_idx = len(args)
                    args.append(unquote_word(bundled))
                    continue
                if word == "-" + short_flag_char:
                    pending_target_dir = True
            continue
        args.append(unquote_word(word))
        if pending_target_dir:
            target_dir_idx = len(args) - 1
            pending_target_dir = False
    return args, target_dir_idx


def _git_paths_tracked(project_dir: str, paths: list[str]) -> bool:
    """True if every path is git-tracked (the path itself, or a dir containing
    a tracked file). Fail-closed: not-a-repo / git error / timeout -> False."""
    rel = [os.path.relpath(p, project_dir) for p in paths]
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false", "ls-files", "--"] + rel,
            cwd=project_dir, capture_output=True, timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False  # fatal (not a git repo, bad pathspec) -> fail closed
    # core.quotePath=false emits raw paths (no C-quoting of non-ASCII names);
    # decode leniently so an unencodable byte can't crash the hook.
    tracked = set(proc.stdout.decode("utf-8", "replace").splitlines())
    for r in rel:
        if r == ".":
            # The repo root "contains a tracked file" iff the repo has any.
            if not tracked:
                return False
            continue
        if not any(t == r or t.startswith(r + "/") for t in tracked):
            return False
    return True


def evaluate_project_file_op(
    norm: list[str], sources: list[dict], project_dir: str
) -> Optional[Decision]:
    """Fallback allow for cp/rm/rmdir/mv/gio trash inside the project dir."""
    name = _cmd_name(norm)
    if name in PROJECT_FILE_OP_COMMANDS:
        after = norm[1:]
    elif name == "gio":
        if len(norm) < 2 or unquote_word(norm[1]) != "trash":
            return None
        after = norm[2:]
    else:
        return None
    args, target_dir_idx = _extract_all_positional_args(
        after, EQUALS_FORM_VALUE_PREFIXES.get(name, ()), SHORT_VALUE_FLAG_CHARS.get(name)
    )
    if not args:
        return None
    project_root = os.path.abspath(project_dir)
    # Which operands the command removes: `cp` removes none (source is read);
    # `mv` removes its sources (the destination is the -t/--target-directory
    # value if present, else the last positional); rm/rmdir/gio-trash remove
    # every operand.
    if name == "cp":
        destructive = [False] * len(args)
    elif name == "mv":
        dest_idx = target_dir_idx if target_dir_idx is not None else len(args) - 1
        destructive = [i != dest_idx for i in range(len(args))]
    else:
        destructive = [True] * len(args)
    resolved: list[str] = []
    for is_destructive, arg in zip(destructive, args):
        expanded = expand_tilde_in_arg(arg)
        abs_p = os.path.abspath(expanded)
        if is_destructive and abs_p == project_root:
            return Decision("deny", None, [arg])
        if abs_p != project_root and not abs_p.startswith(project_root + "/"):
            return None
        if _touches_sensitive_project_dir(abs_p):
            return None
        resolved.append(abs_p)
    op = read_rule_opinion_for_paths(sources, resolved)
    if op is not None:
        return op
    if not _git_paths_tracked(project_root, resolved):
        return None  # not in version control -> fall through to ask
    return Decision("allow")


# ---------------------------------------------------------------------------
# Policy: matching + source precedence
# ---------------------------------------------------------------------------


def _regex_match(pattern: str, target: str) -> bool:
    try:
        return re.search(pattern, target) is not None
    except re.error:
        sys.stderr.write(f"[pre-tool-use] invalid regex in permissions: {pattern}\n")
        return False


def test_pattern(pattern: str, target: str) -> bool:
    return _regex_match(pattern, target)


def expand_tilde_bucket(bucket: dict[str, list[str]]) -> dict[str, list[str]]:
    """Expand `~/` in rule patterns to the absolute home directory."""
    home = os.path.expanduser("~")
    out: dict[str, list[str]] = {}
    for key, pats in bucket.items():
        out[key] = [
            p.replace("~/", home + "/") if "~/" in p else p for p in pats
        ]
    return out


def expand_grouped_keys(bucket: dict[str, list[str]]) -> dict[str, list[str]]:
    """Expand `|`-grouped tool keys (`"Bash|Edit"`) into individual keys."""
    out: dict[str, list[str]] = {}
    for key, pats in bucket.items():
        for k in key.split("|"):
            k = k.strip()
            if k:
                out.setdefault(k, []).extend(pats)
    return out


def matches_bucket(bucket: dict[str, list[str]], tool_name: str, target: str) -> Optional[str]:
    pats = bucket.get(tool_name) or []
    for p in pats:
        if test_pattern(p, target):
            return p
    return None


def bucket_opinion(
    bucket: dict[str, list[str]], tool_name: str, target: str
) -> Optional[tuple[str, Optional[str]]]:
    """Within one source's opinion bucket: allow > ask > deny."""
    for kind in ("allow", "ask", "deny"):
        pat = matches_bucket(bucket.get(kind, {}), tool_name, target)
        if pat is not None:
            return kind, pat
    return None


def prioritized_opinion(
    sources: list[dict], tool_name: str, target: str
) -> Optional[Decision]:
    """First matching source wins (sources already ordered most-important-first)."""
    for source in sources:
        for kind in ("allow", "ask", "deny"):
            pat = matches_bucket(source.get(kind, {}), tool_name, target)
            if pat is not None:
                return Decision(kind, pat)
    return None


def matches_deny(sources: list[dict], tool_name: str, target: str) -> Optional[str]:
    """Return the first matching deny pattern across sources, else None.

    Used for declared-function calls: a deny rule on the call itself still wins
    over the implicit function-call allow (deny > allow), but allow/ask rules are
    ignored — a function invocation is not a tool call.
    """
    for source in sources:
        pat = matches_bucket(source.get("deny", {}), tool_name, target)
        if pat is not None:
            return pat
    return None


# ---------------------------------------------------------------------------
# Self-protection guard
# ---------------------------------------------------------------------------


def edits_protected_file(tool_name: str, target: Optional[str]) -> bool:
    if tool_name not in MUTATING_FILE_TOOLS and tool_name != "Bash":
        return False
    if not target:
        return False
    return PROTECTED_FILE_RE.search(target) is not None


def get_match_target(tool_name: str, tool_input: dict) -> Optional[str]:
    if tool_name == "Bash":
        return tool_input.get("command")
    if tool_name in ("Read", "Edit", "MultiEdit", "Write"):
        return tool_input.get("file_path")
    if tool_name == "NotebookEdit":
        return tool_input.get("notebook_path")
    if tool_name == "WebSearch":
        return tool_input.get("query")
    if tool_name == "WebFetch":
        return tool_input.get("url")
    if tool_name == "Skill":
        return tool_input.get("skill")
    return tool_input.get("command") or tool_input.get("path")


# ---------------------------------------------------------------------------
# Core evaluation: walker + per-command pipeline
# ---------------------------------------------------------------------------


def _aggregate(results: list[Decision]) -> Decision:
    for r in results:
        if r.decision == "deny":
            return r
    asks = [r for r in results if r.decision == "ask"]
    if asks:
        cmds: list[str] = []
        for r in asks:
            if r.cmds:
                cmds.extend(r.cmds)
        return Decision("ask", None, cmds)
    return Decision("allow")


def _collect_cond_terms(node: list[Any]) -> list[str]:
    head = node[0]
    if head == "cond-term":
        return [node[1]]
    out: list[str] = []
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] in ("cond", "cond-unary", "cond-term"):
            out.extend(_collect_cond_terms(child))
    return out


def _flow_path_arg_decision(
    sources: list[dict], raw_words: list[str], display: Optional[str] = None
) -> Optional[Decision]:
    paths = extract_path_args(raw_words)
    if not paths:
        return None
    op = read_rule_opinion_for_paths(sources, paths)
    if op is None:
        return None
    return Decision(op.decision, op.pattern, [display or " ".join(raw_words)])


def _walk_for_like(
    node: list[Any], sources: list[dict], tool_name: str, declared: set[str]
) -> list[Decision]:
    out: list[Decision] = []
    kw = node[0].name
    var = node[1][1] if isinstance(node[1], list) and node[1] and node[1][0] == "word" else ""
    in_node = node[2]
    in_words = [w[1] for w in in_node[1:] if isinstance(w, list) and w and w[0] == "word"]
    header = f"{kw} {var} in {' '.join(in_words)}"
    pr = _flow_path_arg_decision(sources, in_words, header)
    if pr is not None:
        out.append(pr)
    out.extend(walk(node[3], sources, tool_name, declared))
    return out


def _walk_case(
    node: list[Any], sources: list[dict], tool_name: str, declared: set[str]
) -> list[Decision]:
    out: list[Decision] = []
    subj = node[1]
    if isinstance(subj, list) and subj and subj[0] == "word":
        pr = _flow_path_arg_decision(sources, [subj[1]])
        if pr is not None:
            out.append(pr)
    for pattern_node in node[2:]:
        if not (isinstance(pattern_node, list) and pattern_node and pattern_node[0] == "pattern"):
            continue
        words_node = pattern_node[1]
        pat_words = [
            w[1]
            for w in words_node
            if isinstance(w, list) and w and w[0] == "word"
        ]
        pr = _flow_path_arg_decision(sources, pat_words)
        if pr is not None:
            out.append(pr)
        if len(pattern_node) > 2:
            out.extend(walk(pattern_node[2], sources, tool_name, declared))
    return out


def _walk_cond(node: list[Any], sources: list[dict]) -> list[Decision]:
    results: list[Decision] = []
    for term in _collect_cond_terms(node):
        if _unsafe_text(term):
            results.append(Decision("ask", None, [term]))
        paths = extract_path_args([term])
        if paths:
            op = read_rule_opinion_for_paths(sources, paths)
            if op is not None:
                results.append(Decision(op.decision, op.pattern, [term]))
    return results


def _walk_arith_for(
    node: list[Any], sources: list[dict], tool_name: str, declared: set[str]
) -> list[Decision]:
    results: list[Decision] = []
    for child in node[1:-1]:
        if isinstance(child, list) and child and child[0] in ("init", "test", "step"):
            for w_node in child[1:]:
                if isinstance(w_node, list) and w_node and w_node[0] == "word":
                    if _unsafe_text(w_node[1]):
                        results.append(Decision("ask", None, [w_node[1]]))
    results.extend(walk(node[-1], sources, tool_name, declared))
    return results


def walk(
    node: list[Any], sources: list[dict], tool_name: str, declared: set[str]
) -> list[Decision]:
    """In-order DFS over the AST; returns every leaf command's decision.

    `declared` accumulates function names as their definitions are walked, in
    source order, so a later call to an earlier-defined function is not mistaken
    for a tool call.
    """
    if not isinstance(node, list) or not node:
        return [Decision("allow")]
    head = node[0]
    if head == "command":
        return [evaluate_command(node, sources, tool_name, declared)]
    if head in ("and", "or", "semi", "pipe", "background"):
        out: list[Decision] = []
        for child in node[1:]:
            out.extend(walk(child, sources, tool_name, declared))
        return out
    if head in ("subshell", "brace-group", "negation"):
        return walk(node[1], sources, tool_name, declared)
    if head == "time":
        for child in node[1:]:
            if isinstance(child, list):
                return walk(child, sources, tool_name, declared)
        return [Decision("allow")]
    if head in ("if", "while", "until"):
        out = []
        for child in node[1:]:
            out.extend(walk(child, sources, tool_name, declared))
        return out
    if head in ("for", "select"):
        return _walk_for_like(node, sources, tool_name, declared)
    if head == "case":
        return _walk_case(node, sources, tool_name, declared)
    if head == "arith-for":
        return _walk_arith_for(node, sources, tool_name, declared)
    if head in ("cond", "cond-unary"):
        return _walk_cond(node, sources)
    if head == "function":
        # Record the name before walking the body so a self-recursive call
        # (`f() { f; }`) is also recognized. The body is still walked (and its
        # commands vetted) exactly as before — the declaration itself is not a
        # decision; only the body's commands are.
        if len(node) > 1 and isinstance(node[1], str):
            declared.add(unquote_word(node[1]))
        return walk(node[2], sources, tool_name, declared)
    if head == "coproc":
        return walk(node[2], sources, tool_name, declared)
    if head == "arith":
        words = [
            c[1]
            for c in node[1:]
            if isinstance(c, list) and c and c[0] == "word"
        ]
        return [Decision("ask", None, [" ".join(words) or "(arithmetic)"])]
    if head == "redirect":
        return [Decision("allow")]
    sys.stderr.write(f"[pre-tool-use] unknown AST node kind: {head}\n")
    return [Decision("ask", None, ["(unknown)"])]


def evaluate_command(
    node: list[Any], sources: list[dict], tool_name: str, declared: set[str]
) -> Decision:
    """The 10-step per-command pipeline."""
    words, redirects = _split_command(node)

    # 1. Empty command (or comment-only) → allow.
    if not words and not redirects:
        return Decision("allow")

    # 2. Assignment with command-substitution RHS → recurse into the body.
    if not redirects:
        bodies = extract_assignment_substitutions(words)
        if bodies is not None:
            # The body runs in a subshell where already-declared functions are
            # visible, but a function defined *inside* the substitution does not
            # leak back out — pass a copy so inner definitions stay scoped.
            return evaluate(bodies, sources, tool_name, set(declared))

    # 2b. Pure assignment command (`ids="$1"`, `export X=1`) — no command name,
    # so nothing external runs. Allow it unless a substitution or write-redirect
    # hazard remains (the single-`$(…)` form was already recursed in step 2).
    if _is_assignment_only(words):
        if unsafe_construct(words, redirects):
            return Decision("ask", None, [render_match_string(words, redirects)])
        return Decision("allow")

    norm = normalize_words(words)
    match = render_match_string(norm, redirects)
    cmd_name = _cmd_name(norm)

    # `eval` re-parses its argument string as shell code (and `builtin eval` /
    # `command eval` strip down to it), so its inner commands are invisible to the
    # parser. Never transparent — fail closed to ask, mirroring `sh -c`.
    if tool_name == "Bash" and cmd_name == "eval":
        return Decision("ask", None, [match])

    # 3. stdin-only sed fast path.
    if tool_name == "Bash" and cmd_name == "sed" and is_safe_sed_stdin_only(norm):
        if unsafe_construct(words, redirects):
            return Decision("ask", None, [match])
        if edits_protected_file(tool_name, match):
            return Decision("ask", None, [match])
        return Decision("allow")

    # 4. xargs delegation.
    if tool_name == "Bash" and cmd_name == "xargs":
        inner = extract_xargs_inner(norm)
        if inner is not None:
            deny = prioritized_opinion(sources, "Bash", match)
            if deny is not None and deny.decision == "deny":
                return deny
            if unsafe_construct(words, redirects):
                return Decision("ask", None, [match])
            # Delegating drops `-a FILE`'s value and the outer redirect targets,
            # both of which xargs reads. Re-apply the read-path protection on them
            # so `xargs -a ~/.ssh/id_rsa echo` can't sidestep `cat ~/.ssh/id_rsa`.
            path_words = extract_redirect_path_args(redirects)
            arg_file = extract_xargs_arg_file(norm)
            if arg_file is not None:
                path_words.append(arg_file)
            pr = read_rule_opinion_for_paths(sources, extract_path_args(path_words))
            if pr is not None:
                return Decision(pr.decision, pr.pattern, [match])
            return evaluate(" ".join(inner), sources, tool_name)

    # 5. Policy opinion — unless this is a bare call to a function declared
    # earlier in this command. A declared function's body was already walked and
    # vetted at its declaration site, so its invocation is not a tool call: it
    # is implicitly allowed rather than hitting the "unknown command → ask"
    # default. A deny rule on the call itself still wins (deny > allow), and the
    # structural/path guards in step 7 still apply to the call's arguments.
    if tool_name == "Bash" and _is_bare_function_call(words, declared):
        deny_pat = matches_deny(sources, tool_name, match)
        decision = (
            Decision("deny", deny_pat) if deny_pat is not None else Decision("allow")
        )
    else:
        decision = prioritized_opinion(sources, tool_name, match)

    # 5b. WebFetch URL delegation for plain wget/curl fetches (overrides the
    # blanket `^(curl|wget)\s` ask; a Bash deny still wins).
    if (
        tool_name == "Bash"
        and cmd_name in {"wget", "curl"}
        and (decision is None or decision.decision != "deny")
    ):
        wf = evaluate_web_fetch(norm, sources)
        if wf is not None:
            decision = wf

    # 6. Implicit allows (no policy rule matched).
    if decision is None and tool_name == "Bash" and cmd_name == "sed" and is_safe_sed(norm):
        decision = Decision("allow")
    if decision is None and tool_name == "Bash" and cmd_name == "sed" and is_safe_sed_in_place(norm, sources):
        decision = Decision("allow")
    if decision is None and tool_name == "Bash" and cmd_name in {"awk", "gawk", "mawk", "nawk"} and is_safe_awk(norm):
        decision = Decision("allow")
    if decision is None and tool_name == "Bash":
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if project_dir:
            decision = evaluate_project_file_op(norm, sources, project_dir)

    # 7. Guards on allow decisions + explicit result.
    if decision is not None:
        if decision.decision == "allow":
            if tool_name == "Bash" and unsafe_construct(words, redirects):
                return Decision("ask", None, [match])
            if tool_name == "Bash" and norm:
                path_words = norm[1:] + extract_redirect_path_args(redirects)
                pr = read_rule_opinion_for_paths(sources, extract_path_args(path_words))
                if pr is not None:
                    return Decision(pr.decision, pr.pattern, [match])
        if decision.decision == "allow" and edits_protected_file(tool_name, match):
            return Decision("ask", None, [match])
        return Decision(decision.decision, decision.pattern, [match])

    # 8. Defaults.
    if tool_name in FILE_TOOLS:
        decision = Decision("allow")
    else:
        restricted = any(
            len(source.get("allow", {}).get(tool_name, [])) > 0 for source in sources
        )
        decision = Decision("ask" if (tool_name == "Bash" or restricted) else "allow")

    if decision.decision == "allow" and edits_protected_file(tool_name, match):
        return Decision("ask", None, [match])
    return Decision(decision.decision, decision.pattern, [match])


def evaluate(
    source: str,
    sources: list[dict],
    tool_name: str,
    declared: Optional[set[str]] = None,
) -> Decision:
    """Parse source and aggregate every leaf command's decision.

    `declared` tracks functions defined in the source so far, so a call to a
    declared function is not mistaken for a tool call. Callers that re-parse a
    sub-command in a different execution context (e.g. `xargs`'s inner command)
    pass `None` to start a fresh scope.
    """
    if declared is None:
        declared = set()
    try:
        nodes = parse_command(source)
    except UnparseableCommand:
        return Decision("ask", None, [source.strip() or EMPTY_CMD])
    if not nodes:
        return Decision("ask", None, [EMPTY_CMD])
    results: list[Decision] = []
    for node in nodes:
        results.extend(walk(node, sources, tool_name, declared))
    return _aggregate(results)


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def _read_json_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _opinion_to_buckets(opinion: dict) -> dict[str, dict[str, list[str]]]:
    buckets: dict[str, dict[str, list[str]]] = {}
    for kind in ("allow", "ask", "deny"):
        raw = opinion.get(kind, {})
        expanded = expand_grouped_keys(expand_tilde_bucket(raw))
        buckets[kind] = expanded
    return buckets


def load_permissions() -> list[dict]:
    """Load sources most-important-first; global required (fail-open)."""
    sources: list[dict] = []

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        local = _read_json_file(
            os.path.join(project_dir, ".claude", "permissions.local.json")
        )
        if local:
            sources.append(_opinion_to_buckets(local))
        proj = _read_json_file(
            os.path.join(project_dir, ".claude", "permissions.json")
        )
        if proj:
            sources.append(_opinion_to_buckets(proj))

    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    global_path = os.path.join(config_dir, "permissions.json")
    try:
        with open(global_path, "r", encoding="utf-8") as f:
            global_policy = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[pre-tool-use] Failed to load permissions.json: {e}\n")
        # Fail open — don't block all tool calls when the policy file is unreadable.
        sys.exit(0)
    sources.append(_opinion_to_buckets(global_policy))

    return sources


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


class _A:
    """ANSI SGR codes, mirroring the legacy hook's colored stderr output."""

    reset = "\x1b[0m"
    bold = "\x1b[1m"
    red = "\x1b[31m"
    cyan = "\x1b[36m"
    yellow = "\x1b[33m"


def fmt_cmd(s: Optional[str], max_len: int = 300) -> str:
    if s is None:
        return ""
    return s[:max_len] + "…" if len(s) > max_len else s


def stderr_deny(tool_name: str, cmd: Optional[str], pattern: Optional[str]) -> None:
    cmd_line = f"  {_A.bold}Command:{_A.reset} {_A.cyan}{fmt_cmd(cmd)}{_A.reset}\n" if cmd else ""
    pat_line = f"  {_A.bold}Pattern:{_A.reset} {pattern}\n" if pattern else ""
    sys.stderr.write(
        f"\n{_A.bold}{_A.red}✗ DENIED{_A.reset} — {tool_name}\n{cmd_line}{pat_line}\n"
    )


def stderr_ask(tool_name: str, cmds: list[str]) -> None:
    lines = "\n".join(f"  {_A.cyan}{fmt_cmd(c)}{_A.reset}" for c in cmds)
    sys.stderr.write(
        f"\n{_A.bold}{_A.yellow}? ASK{_A.reset} — {tool_name} (needs approval)\n{lines}\n\n"
    )


def out(decision: str, reason: Optional[str] = None) -> None:
    payload: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        payload["hookSpecificOutput"]["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(payload))


def _count_leaves(node: Any) -> int:
    if not isinstance(node, list) or not node:
        return 0
    head = node[0]
    if head in ("command", "arith", "redirect"):
        return 1
    return sum(_count_leaves(c) for c in node[1:] if isinstance(c, list))


def _is_multi_source(source: str) -> bool:
    """True when source splits into >1 sub-command (or is a flow/compound node)."""
    try:
        nodes = parse_command(source)
    except UnparseableCommand:
        return False
    if len(nodes) != 1:
        return True
    top = nodes[0]
    return _count_leaves(top) > 1 or top[0] in (
        "and", "or", "semi", "pipe", "background", "subshell", "brace-group",
        "if", "while", "until", "for", "select", "case", "arith-for", "cond",
    )


def decide_bash(sources: list[dict], target: str) -> None:
    res = evaluate(target, sources, "Bash")
    if res.decision == "deny":
        subcmd = (res.cmds or [target])[0]
        pattern = res.pattern
        stderr_deny("Bash", subcmd, pattern)
        section = (
            f"\n\nBlocking sub-command:\n  {fmt_cmd(subcmd)}"
            if _is_multi_source(target)
            else f"\n\nCommand:\n  {fmt_cmd(subcmd)}"
        )
        reason = f"Command blocked by deny rule{section}"
        if pattern:
            reason += f"\n\nMatched pattern:  {pattern}"
        out("deny", reason)
    elif res.decision == "ask":
        cmds = res.cmds or [target]
        stderr_ask("Bash", cmds)
        label = "Sub-commands need approval" if len(cmds) > 1 else "Command needs approval"
        listing = "\n".join(f"  {fmt_cmd(c)}" for c in cmds)
        out("ask", f"{label}:\n\n{listing}")
    else:
        out("allow")


def _eval_non_bash(sources: list[dict], tool_name: str, target: Optional[str]) -> Decision:
    decision = prioritized_opinion(sources, tool_name, target or "")
    if decision is not None:
        if decision.decision == "allow" and edits_protected_file(tool_name, target):
            return Decision("ask", None, [target] if target else [])
        return decision
    if tool_name in FILE_TOOLS:
        decision = Decision("allow")
    else:
        restricted = any(
            len(source.get("allow", {}).get(tool_name, [])) > 0 for source in sources
        )
        decision = Decision("ask" if restricted else "allow")
    if decision.decision == "allow" and edits_protected_file(tool_name, target):
        return Decision("ask", None, [target] if target else [])
    return decision


def decide(sources: list[dict], tool_name: str, tool_input: dict) -> None:
    effective = "WebFetch" if tool_name == "Fetch" else tool_name
    target = get_match_target(effective, tool_input)
    if effective == "Bash" and target is not None:
        decide_bash(sources, target)
        return
    result = _eval_non_bash(sources, effective, target)
    if result.decision == "deny":
        stderr_deny(tool_name, target, result.pattern)
        reason = f"{tool_name} call blocked by deny rule"
        if target:
            reason += f"\n\nTarget:\n  {fmt_cmd(target)}"
        if result.pattern:
            reason += f"\n\nMatched pattern:  {result.pattern}"
        out("deny", reason)
    elif result.decision == "allow":
        out("allow")
    else:
        if target:
            stderr_ask(tool_name, [target])
        reason = (
            f"{tool_name} call needs approval:\n\n  {fmt_cmd(target)}" if target else None
        )
        out("ask", reason)


def _read_hook_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"[pre-tool-use] failed to parse hook input: {e}\n")
        sys.exit(0)


def main() -> None:
    sources = load_permissions()
    hook_input = _read_hook_input()
    decide(
        sources,
        hook_input.get("tool_name", ""),
        hook_input.get("tool_input", {}),
    )


if __name__ == "__main__":
    main()
