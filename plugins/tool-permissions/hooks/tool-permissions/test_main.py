"""pytest suite for the tool-permissions hook.

Imports the real ``main`` module — no re-pasted copies — so the suite stays
green as the implementation drifts. See CLAUDE.md "Test structure" for the
section map.
"""

import json
import os
import re
import subprocess

import pytest

import main


# Resolve the real home dir at runtime so the suite never hard-codes a
# user-specific path (mirrors the hook's own `os.path.expanduser("~")`).
HOME = os.path.expanduser("~")
HOME_RE = re.escape(HOME)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def src(allow=None, ask=None, deny=None):
    """Build a single policy source with already-expanded tool keys."""
    return {"allow": allow or {}, "ask": ask or {}, "deny": deny or {}}


def ev(cmd, *sources, tool="Bash"):
    """Evaluate a Bash (or other) command against synthetic sources."""
    return main.evaluate(cmd, list(sources), tool)


def decide_decision(capsys, sources, tool_name, tool_input):
    """Run ``decide`` and return the parsed permissionDecision from stdout."""
    main.decide(sources, tool_name, tool_input)
    payload = json.loads(capsys.readouterr().out)
    return payload["hookSpecificOutput"]["permissionDecision"]


# ---------------------------------------------------------------------------
# 1. read_sexp
# ---------------------------------------------------------------------------


def test_read_sexp_word_escapes():
    assert main.read_sexp(r'(word "a\"b")') == ["word", 'a"b']
    assert main.read_sexp(r'(word "a\\b")') == ["word", "a\\b"]
    assert main.read_sexp(r'(word "line\nbreak")') == ["word", "line\nbreak"]
    assert main.read_sexp(r'(word "tab\there")') == ["word", "tab\there"]


def test_read_sexp_verbatim_redirect_target():
    # rable writes redirect targets verbatim (no escaping) inside delim quotes.
    assert main.read_sexp(r'(redirect ">" ""my file.txt"")') == [
        "redirect", ">", '"my file.txt"',
    ]


def test_read_sexp_heredoc_real_newline():
    assert main.read_sexp('(redirect "<<" "hello $(date)\n")') == [
        "redirect", "<<", "hello $(date)\n",
    ]


def test_read_sexp_ints_symbols_empty_roundtrip():
    assert main.read_sexp('(redirect ">&" 1)') == ["redirect", ">&", 1]
    assert main.read_sexp("(command)") == ["command"]
    assert main.read_sexp('(word "")') == ["word", ""]
    assert main.read_sexp('(command (word "cat") (word "file with spaces.txt"))') == [
        "command", ["word", "cat"], ["word", "file with spaces.txt"],
    ]
    # cond-term is verbatim, so the raw quotes survive.
    assert main.read_sexp(r'(cond (cond-unary "-z" (cond-term ""$x"")))') == [
        "cond", ["cond-unary", "-z", ["cond-term", '"$x"']],
    ]


# ---------------------------------------------------------------------------
# 2. Fail-closed unparseable input
# ---------------------------------------------------------------------------


def test_fail_closed_unparseable():
    for bad in ["(echo hi", "done", "fi", "if", "case", "esac", "while", "for"]:
        assert ev(bad).decision == "ask", bad


def test_trust_parser_unclosed_quote():
    # rable drops the unclosed-quote word; `echo` is what executes.
    r = ev('echo "unclosed')
    assert r.decision == "ask"
    assert r.cmds == ["echo"]


def test_bare_flow_keywords_parse_as_empty():
    # Documented deviation: bare do/then/else/elif parse as empty -> allow.
    for kw in ["do", "then", "else", "elif"]:
        assert ev(kw).decision == "allow", kw


# ---------------------------------------------------------------------------
# 3. Empty handling
# ---------------------------------------------------------------------------


def test_empty_handling():
    assert ev("").decision == "ask"
    assert ev("").cmds == ["(empty)"]
    assert ev("# comment").cmds == ["(empty)"]
    assert ev(";").decision == "allow"


# ---------------------------------------------------------------------------
# 4. Compound-list aggregation
# ---------------------------------------------------------------------------


def test_aggregation_first_deny_wins():
    r = ev("git status; git push; git log", src(deny={"Bash": ["^git push"]}))
    assert r.decision == "deny"
    assert r.pattern == "^git push"
    assert r.cmds == ["git push"]


def test_aggregation_all_asks_listed():
    r = ev("echo hi & echo bye")
    assert r.decision == "ask"
    assert r.cmds == ["echo hi", "echo bye"]


def test_aggregation_pipe_bare_redirect_child():
    # `|&` becomes a bare `(redirect ">&" 1)` pipe child on the left command.
    r = ev("echo hi |& cat")
    assert r.decision == "ask"
    assert "echo hi >& 1" in r.cmds
    assert "cat" in r.cmds


def test_aggregation_unsafe_sibling_filtered():
    # allow `echo`; the `$(cmd)` sibling is unsafe -> only it is listed as ask.
    r = ev("echo hi; echo $(cmd)", src(allow={"Bash": ["^echo"]}))
    assert r.decision == "ask"
    assert r.cmds == ["echo $(cmd)"]


# ---------------------------------------------------------------------------
# 5. Flow control (full evaluation)
# ---------------------------------------------------------------------------


def test_flow_if_elif_else():
    s = src(deny={"Bash": ["^ssh"]})
    assert ev("if ssh host; then echo ok; fi", s).decision == "deny"
    assert ev(
        "if false; then echo a; elif ssh host; then echo b; else echo c; fi", s
    ).decision == "deny"


def test_flow_while_until():
    s = src(deny={"Bash": ["^ssh"]})
    assert ev("while ssh host; do echo x; done", s).decision == "deny"
    assert ev("until ssh host; do echo x; done", s).decision == "deny"


def test_flow_for_path_arg():
    s = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    r = ev("for f in ~/.ssh/*; do cat $f; done", s)
    assert r.decision == "deny"


def test_flow_for_dollar_at_noop():
    r = ev('for x in "$@"; do echo $x; done')
    assert r.decision == "ask"
    assert r.cmds == ["echo $x"]


def test_flow_select_empty_in():
    r = ev("select x in; do echo $x; done")
    assert r.decision == "ask"


def test_flow_arith_for():
    r = ev("for ((i=0; i<3; i++)); do echo $i; done")
    assert r.decision == "ask"


def test_flow_case_all_bodies():
    s = src(deny={"Bash": ["^ssh"]})
    r = ev("case $x in a) ssh host;; b) echo ok;; esac", s)
    assert r.decision == "deny"


def test_flow_case_empty_body():
    r = ev("case $x in a);; b) echo ok;; esac")
    assert r.decision == "ask"
    assert r.cmds == ["echo ok"]


def test_flow_case_pattern_path_arg():
    s = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    r = ev("case $x in ~/.ssh/*) echo secret;; esac", s)
    assert r.decision == "deny"


def test_flow_cond_term_path_arg():
    s = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("[[ -f ~/.ssh/id_rsa ]]", s).decision == "deny"


def test_flow_cond_term_unsafe():
    assert ev('[[ -n "$(cmd)" ]]').decision == "ask"


def test_flow_function():
    assert ev("foo() { ssh host; }", src(deny={"Bash": ["^ssh"]})).decision == "deny"


def test_flow_function_call_allowed():
    # A call to a declared function is not a tool call: its body was already
    # vetted, so it should not fall through to the unknown-command "ask".
    s = src(allow={"Bash": ["^echo\\b"]})
    assert ev("greet() { echo hi; }; greet world", s).decision == "allow"
    assert ev("greet() { echo hi; }; greet world", s).cmds is None


def test_flow_function_call_body_still_vetted():
    # The declaration walks the body, so a denied body still denies the whole
    # command even though the call itself would be auto-allowed.
    s = src(allow={"Bash": ["^echo\\b"]}, deny={"Bash": ["^ssh"]})
    assert ev("f() { ssh host; }; f", s).decision == "deny"
    assert ev("f() { echo hi; }; f() { ssh host; }; f", s).decision == "deny"


def test_flow_function_call_unsafe_arg():
    # Auto-allow does not bypass the structural guard on the call's arguments.
    s = src(allow={"Bash": ["^echo\\b"]})
    assert ev("f() { echo hi; }; f $(rm -rf ~)", s).decision == "ask"


def test_flow_function_call_deny_name_wins():
    # A deny rule on the call itself still beats the implicit function-call allow.
    s = src(allow={"Bash": ["^echo\\b"]}, deny={"Bash": ["^evil$"]})
    assert ev("evil() { echo hi; }; evil", s).decision == "deny"


def test_flow_function_call_wrapper_not_bare():
    # `command f` runs an external command, not the function — no auto-allow.
    s = src(allow={"Bash": ["^echo\\b"]})
    assert ev("f() { echo hi; }; command f", s).decision == "ask"


def test_flow_function_call_path_arg_guard():
    # The call's arguments still get path-argument checking.
    s = src(allow={"Bash": ["^echo\\b"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("f() { echo hi; }; f ~/.ssh/id_rsa", s).decision == "deny"


def test_flow_function_nested_and_recursive():
    s = src(allow={"Bash": ["^echo\\b"]})
    assert ev("outer() { inner() { echo hi; }; inner; }; outer", s).decision == "allow"
    assert ev("f() { echo hi; f; }", s).decision == "allow"


def test_flow_function_call_before_def_asks():
    # Source order matters: a call before the declaration is not a function call.
    s = src(allow={"Bash": ["^echo\\b"]})
    assert ev("f; f() { echo hi; }", s).decision == "ask"


def test_flow_coproc():
    assert ev("coproc x { ssh host; }", src(deny={"Bash": ["^ssh"]})).decision == "deny"


def test_flow_arith_ask():
    assert ev("((1+2))").decision == "ask"


def test_flow_time():
    s = src(deny={"Bash": ["^ssh"]})
    assert ev("time ssh host", s).decision == "deny"
    assert ev("time -p ssh host", s).decision == "deny"


def test_flow_negation():
    assert ev("! ssh host", src(deny={"Bash": ["^ssh"]})).decision == "deny"
    # negation is dropped by rable: `! ! true` == `true`.
    assert ev("! ! true").decision == "ask"
    assert ev("! ! true").cmds == ["true"]


# ---------------------------------------------------------------------------
# 6. Structural allow guard (unsafe_construct)
# ---------------------------------------------------------------------------


def test_unsafe_construct_words():
    assert main.unsafe_construct(["echo", "$(cmd)"], []) is True
    assert main.unsafe_construct(["echo", "$((1+2))"], []) is False
    assert main.unsafe_construct(["echo", "$((x + $(cmd)))"], []) is True
    assert main.unsafe_construct(["echo", "`cmd`"], []) is True
    assert main.unsafe_construct(["echo", "${x@P}"], []) is True
    assert main.unsafe_construct(["cat", "<(x)"], []) is True
    assert main.unsafe_construct(["cat", ">(x)"], []) is True
    assert main.unsafe_construct(["echo", "'$(cmd)'"], []) is False


def test_unsafe_construct_prompt_expansion():
    # ${var@P} prompt-string expansion is flagged for any parameter-name length.
    assert main.unsafe_construct(["echo", "${x@P}"], []) is True
    assert main.unsafe_construct(["echo", "${foo@P}"], []) is True
    assert main.unsafe_construct(["echo", "${PATH@P}"], []) is True
    # other parameter transforms are not command-execution vectors.
    assert main.unsafe_construct(["echo", "${x@Q}"], []) is False


def test_unsafe_construct_write_redirects():
    for op in (">", ">>", ">|", "&>", "&>>"):
        assert main.unsafe_construct(["echo"], [(op, "file")]) is True, op
    # string-target fd dup is a write; int target is safe.
    assert main.unsafe_construct(["echo"], [(">&", "output.log")]) is True
    assert main.unsafe_construct(["echo"], [(">&", 1)]) is False
    assert main.unsafe_construct(["echo"], [(">&-", 0)]) is False


def test_unsafe_construct_safe_targets():
    assert main.unsafe_construct(["echo"], [(">", "/dev/null")]) is False
    assert main.unsafe_construct(["echo"], [(">", "/tmp/x")]) is False
    assert main.unsafe_construct(
        ["echo"], [(">", os.path.expanduser("~/.claude/tmp/x"))]
    ) is False
    assert main.unsafe_construct(["echo"], [("<<<", "hi")]) is False


def test_unsafe_construct_heredoc_body():
    assert main.unsafe_construct(["cat"], [("<<", "hello $(date)\n")]) is True


# ---------------------------------------------------------------------------
# 7. Word normalization
# ---------------------------------------------------------------------------


def test_normalize_assignments_and_wrappers():
    assert main.normalize_words(["X=1", "rm", "-rf", "~"]) == ["rm", "-rf", "~"]
    assert main.normalize_words(["command", "rm", "-rf", "~"]) == ["rm", "-rf", "~"]
    assert main.normalize_words(["exec", "rm"]) == ["rm"]
    assert main.normalize_words(["builtin", "echo", "x"]) == ["echo", "x"]
    # `eval` re-parses its args as shell code — NOT a transparent wrapper, so
    # it must be left intact for the evaluator to fail closed.
    assert main.normalize_words(["eval", "echo", "x"]) == ["eval", "echo", "x"]
    assert main.normalize_words(["nohup", "rm"]) == ["rm"]


def test_normalize_command_flags():
    assert main.normalize_words(["command", "-v", "ls"]) == ["command", "-v", "ls"]
    assert main.normalize_words(["command", "-V", "ls"]) == ["command", "-V", "ls"]
    assert main.normalize_words(["command", "-p", "rm"]) == ["rm"]
    assert main.normalize_words(["command", "-P", "rm"]) == ["rm"]
    assert main.normalize_words(["command"]) == ["command"]


def test_normalize_quoted_command_name():
    assert main.normalize_words(['"rm"', "-rf"]) == ["rm", "-rf"]
    assert main.normalize_words(["\\rm", "-rf"]) == ["rm", "-rf"]


def test_normalize_timeout():
    assert main.normalize_words(["timeout", "5", "xargs", "-n", "4", "rg", "p"]) == [
        "xargs", "-n", "4", "rg", "p",
    ]
    assert main.normalize_words(["timeout", "-s", "KILL", "5", "rm"]) == ["rm"]


def test_normalize_env():
    assert main.normalize_words(["env", "ssh", "host"]) == ["ssh", "host"]
    assert main.normalize_words(["env", "FOO=1", "BAR=2", "ssh", "host"]) == ["ssh", "host"]
    assert main.normalize_words(["env", "-i", "FOO=1", "rm", "-rf"]) == ["rm", "-rf"]
    assert main.normalize_words(["env", "-u", "FOO", "ssh"]) == ["ssh"]
    assert main.normalize_words(["env", "--unset=FOO", "ssh"]) == ["ssh"]
    assert main.normalize_words(["env", "--", "ssh", "host"]) == ["ssh", "host"]
    assert main.normalize_words(["env", "-", "ssh", "host"]) == ["ssh", "host"]
    # `-S`/`--split-string` merge their split words with the trailing args, and
    # `-C`/`--chdir` rebase relative paths — both make the inner command opaque,
    # so the wrapper must be left intact (fail-closed)
    assert main.normalize_words(["env", "-S", "FOO=1", "ssh"]) == ["env", "-S", "FOO=1", "ssh"]
    assert main.normalize_words(["env", "-S", "ssh", "host"]) == ["env", "-S", "ssh", "host"]
    assert main.normalize_words(["env", "--split-string=ssh host"]) == ["env", "--split-string=ssh host"]
    assert main.normalize_words(["env", "-C", "~/.ssh", "cat", "id_rsa"]) == ["env", "-C", "~/.ssh", "cat", "id_rsa"]
    assert main.normalize_words(["env", "--chdir=~/.ssh", "ls"]) == ["env", "--chdir=~/.ssh", "ls"]
    # glued short forms are just as opaque -> left intact (fail-closed)
    assert main.normalize_words(["env", "-C~/.ssh", "cat", "id_rsa"]) == ["env", "-C~/.ssh", "cat", "id_rsa"]
    assert main.normalize_words(["env", "-Sssh", "host"]) == ["env", "-Sssh", "host"]
    # assignment-shaped arg after the command is preserved, not stripped
    assert main.normalize_words(["env", "grep", "a=b"]) == ["grep", "a=b"]
    # bare env (no inner command) strips to nothing
    assert main.normalize_words(["env"]) == []


def test_normalize_crlf():
    assert main.normalize_words(["rm", "-rf\r"]) == ["rm", "-rf"]


# ---------------------------------------------------------------------------
# 8. Assignment-substitution recursion
# ---------------------------------------------------------------------------


def test_extract_assignment_substitutions():
    assert main.extract_assignment_substitutions(["X=$(git push)"]) == "git push"
    assert main.extract_assignment_substitutions(["A=$(a)", "B=$(b)"]) == "a; b"
    assert main.extract_assignment_substitutions(["export", "X=$(git push)"]) == "git push"
    assert main.extract_assignment_substitutions(
        ["local", "-a", "X=$(git push)"]
    ) == "git push"
    assert main.extract_assignment_substitutions(["declare", "-r", "X=$(git push)"]) == "git push"
    assert main.extract_assignment_substitutions(["readonly", "X=$(git push)"]) == "git push"
    assert main.extract_assignment_substitutions(["typeset", "X=$(git push)"]) == "git push"
    # not a $(...) RHS -> no recursion
    assert main.extract_assignment_substitutions(["X=foo"]) is None
    # trailing material after the single substitution -> no recursion
    assert main.extract_assignment_substitutions(["X=$(a)$(b)"]) is None


def test_assignment_recursion_deny():
    s = src(deny={"Bash": ["^git push"]})
    assert ev("X=$(git push)", s).decision == "deny"
    assert ev("A=$(git status) B=$(git push)", s).decision == "deny"
    assert ev("export X=$(git push)", s).decision == "deny"
    assert ev("local -a X=$(git push)", s).decision == "deny"


def test_assignment_recursion_no_redirect():
    # a redirect on the assignment word disables recursion (normal eval path).
    assert ev("X=$(git push) > /dev/null", src(deny={"Bash": ["^git push"]})).decision == "ask"


def test_is_assignment_only():
    assert main._is_assignment_only(['ids="$1"'])
    assert main._is_assignment_only(["X=1"])
    assert main._is_assignment_only(["export", "X=1"])
    assert main._is_assignment_only(["local", "-a", "X=1"])
    # a real command name (even a wrapper) is not assignment-only
    assert not main._is_assignment_only(["env"])
    assert not main._is_assignment_only(["env", "FOO=1"])
    assert not main._is_assignment_only(["rm", "-rf", "~"])
    # a bare modifier prints the environment -> not assignment-only
    assert not main._is_assignment_only(["export"])
    assert not main._is_assignment_only([])


def test_assignment_only_allowed():
    # a bare assignment runs nothing external -> allow, and never emits an
    # empty match line in the ask prompt.
    assert ev('ids="$1"').decision == "allow"
    assert ev("X=1").decision == "allow"
    assert ev("export X=1").decision == "allow"
    # a quoted command substitution still fails closed to ask.
    assert ev('X="$(foo)"').decision == "ask"
    # a write redirect on an otherwise assignment-only command is still a write.
    assert ev("X=1 > file").decision == "ask"
    # a safe redirect target stays allow.
    assert ev("X=1 > /dev/null").decision == "allow"


def test_assignment_line_not_in_prompt():
    # Regression: the assignment `ids="$1"` inside a function body used to
    # normalize to an empty command and surface as a blank "" line in the ask
    # prompt. It must be dropped, leaving only the real sub-commands.
    cmd = 'fetch() { ids="$1"; curl -s "https://example.com/?id=$ids" | jq -r .; }\n'
    cmd += 'echo "=== X ==="; fetch "1"'
    r = ev(cmd)
    assert "" not in r.cmds
    assert r.cmds == [
        'curl -s "https://example.com/?id=$ids"',
        "jq -r .",
        'echo "=== X ==="',
    ]


# ---------------------------------------------------------------------------
# 9. Canonical match strings
# ---------------------------------------------------------------------------


def test_match_string_quotes_preserved():
    assert main.render_match_string(["git", "-C", '"dir"', "status"], []) == 'git -C "dir" status'


def test_match_string_canonical_spacing():
    s = src(allow={"Bash": ["^git status"]})
    assert ev("git  status", s).decision == "allow"


def test_match_string_quoted_arg_allows():
    s = src(allow={"Bash": ['^git -C [\'\\"]?\\S+[\'\\"]? status$']})
    assert ev('git -C "dir" status', s).decision == "allow"


# ---------------------------------------------------------------------------
# 10. xargs delegation
# ---------------------------------------------------------------------------


def test_xargs_inner():
    assert main.extract_xargs_inner(["xargs", "-n", "4", "rg", "p"]) == ["rg", "p"]
    assert main.extract_xargs_inner(["xargs", "-I{}", "echo"]) == ["echo"]
    assert main.extract_xargs_inner(["xargs", "-I", "{}", "echo"]) == ["echo"]
    # quirk fix: long value-flags with a separate token
    assert main.extract_xargs_inner(["xargs", "--max-args", "4", "rg", "p"]) == ["rg", "p"]
    assert main.extract_xargs_inner(["xargs", "--max-args=4", "rg", "p"]) == ["rg", "p"]
    # bare -> None
    assert main.extract_xargs_inner(["xargs"]) is None
    # bare stdin consumer gets the synthetic placeholder
    assert main.extract_xargs_inner(["xargs", "rg"]) == ["rg", "__xargs_input__"]
    assert main.extract_xargs_inner(["xargs", "grep", "p"]) == ["grep", "p"]


def test_xargs_deny_first():
    s = src(deny={"Bash": ["^xargs"]})
    assert ev("xargs -n 4 rg pattern", s).decision == "deny"


def test_xargs_unsafe_on_original():
    assert ev("xargs -n 4 echo $(cmd)").decision == "ask"


def test_xargs_timeout_composition():
    # normalize strips `timeout 5`, then xargs delegates to `rg`.
    assert ev("timeout 5 xargs rg pattern").decision == "ask"


def test_xargs_arg_file_path_protected():
    # `xargs -a FILE` (and `< FILE`) read FILE as the item source; delegating to
    # the inner command drops that path, so the read-path protection must re-fire.
    home = re.escape(os.path.expanduser("~"))
    s = src(allow={"Bash": ["^echo(\\s|$)"]}, deny={"Read": [f"^{home}/\\.ssh/.*$"]})
    assert ev("xargs -a ~/.ssh/id_rsa echo", s).decision == "deny"
    assert ev("xargs --arg-file ~/.ssh/id_rsa echo", s).decision == "deny"
    assert ev("xargs --arg-file=~/.ssh/id_rsa echo", s).decision == "deny"
    assert ev("xargs echo < ~/.ssh/id_rsa", s).decision == "deny"
    # a value-flag with a separate token BEFORE `-a` must not hide the arg-file
    assert ev("xargs -n 4 -a ~/.ssh/id_rsa echo", s).decision == "deny"
    assert ev("xargs --max-args 4 -a ~/.ssh/id_rsa echo", s).decision == "deny"
    assert ev("xargs -I {} -a ~/.ssh/id_rsa echo", s).decision == "deny"
    # a benign arg-file still delegates to the (allow-listed) inner command
    assert ev("xargs -a /tmp/list.txt echo", s).decision == "allow"


# ---------------------------------------------------------------------------
# 10b. env delegation (command wrapper)
# ---------------------------------------------------------------------------


def test_env_subcommand_evaluated_separately():
    s = src(deny={"Bash": ["^ssh"]})
    assert ev("env ssh host", s).decision == "deny"
    assert ev("env FOO=1 ssh host", s).decision == "deny"
    assert ev("env -i FOO=1 ssh host", s).decision == "deny"


def test_env_allow_subcommand():
    s = src(allow={"Bash": ["^git status"]})
    assert ev("env FOO=1 git status", s).decision == "allow"


def test_env_unsafe_on_original():
    # the structural allow guard runs on the original `env …` words.
    assert ev("env FOO=1 echo $(cmd)", src(allow={"Bash": ["^echo"]})).decision == "ask"


def test_env_bare_asks():
    assert ev("env").decision == "ask"


def test_wrappers_evaluate_subcommand_separately():
    # every wrapper resolves to its inner command, so a deny on the inner name
    # fires regardless of the dressing.
    s = src(deny={"Bash": ["^ssh"]})
    for cmd in [
        "time ssh host",
        "timeout 5 ssh host",
        "nohup ssh host",
        "env ssh host",
        "xargs ssh host",
    ]:
        assert ev(cmd, s).decision == "deny", cmd


def test_wrapper_path_forms_delegate():
    # `/usr/bin/env`, `/bin/timeout`, `/usr/bin/nohup` resolve to their basename
    # and delegate the same as the bare names (deny on the inner name still fires).
    s = src(deny={"Bash": ["^ssh"]}, allow={"Bash": ["^git status"]})
    for cmd in [
        "/usr/bin/env ssh host",
        "/bin/env ssh host",
        "/usr/bin/timeout 5 ssh host",
        "/usr/bin/nohup ssh host",
        "command /usr/bin/env ssh host",
    ]:
        assert ev(cmd, s).decision == "deny", cmd
    assert ev("/usr/bin/env git status", s).decision == "allow"
    assert ev("/usr/bin/nohup git status", s).decision == "allow"


def test_env_opaque_flags_not_delegated():
    # `env -S 'ssh' host x` actually runs `ssh host x` (split words merge with the
    # trailing args); `env -C ~/.ssh cat id_rsa` chdirs so `id_rsa` is the key.
    # Both make the inner command opaque — the wrapper must stay intact -> ask.
    s = src(allow={"Bash": ["^host\\s", "^cat(\\s|$)", "^ls(\\s|$)"]}, deny={"Bash": ["^ssh"]})
    assert ev("env -S ssh host example.com", s).decision == "ask"
    assert ev("env --split-string ssh host example.com", s).decision == "ask"
    assert ev("env --split-string=ssh host", s).decision == "ask"
    assert ev("env -C ~/.ssh cat id_rsa", s).decision == "ask"
    assert ev("env --chdir ~/.ssh ls", s).decision == "ask"
    assert ev("env --chdir=~/.ssh ls", s).decision == "ask"
    # glued short forms must not slip through the opaque-flag guard
    assert ev("env -C~/.ssh cat id_rsa", s).decision == "ask"
    assert ev("env -Sssh host example.com", s).decision == "ask"


def test_eval_fails_closed():
    # `eval` re-parses its argument string as shell code, so `eval "echo; ssh"`
    # actually runs BOTH `echo` and `ssh`; stripping would match `^echo` and
    # silently pass `ssh`. It must fail closed to ask (like `sh -c`).
    s = src(allow={"Bash": ["^echo(\\s|$)", "^host\\s"]}, deny={"Bash": ["^ssh"]})
    assert ev('eval "echo hi; ssh host"', s).decision == "ask"
    assert ev("eval 'ssh host'", s).decision == "ask"
    assert ev("eval ssh host", s).decision == "ask"
    assert ev("builtin eval 'ssh host'", s).decision == "ask"
    assert ev("command eval 'ssh host'", s).decision == "ask"


# ---------------------------------------------------------------------------
# 11. sed safety
# ---------------------------------------------------------------------------


def test_sed_safe_forms():
    assert main.is_safe_sed(["sed", "s/a/b/"]) is True
    assert main.is_safe_sed(["sed", "s/a/b/", "f"]) is True
    assert main.is_safe_sed(["sed", "-n", "s/a/b/p"]) is True
    assert main.is_safe_sed(["sed", "s/a/b/e"]) is False
    assert main.is_safe_sed(["sed", "s/a/b/w"]) is False
    assert main.is_safe_sed(["sed", "-i", "s/a/b/", "f"]) is False
    assert main.is_safe_sed(["sed", "-f", "scr", "f"]) is False


def test_sed_script():
    assert main.is_safe_sed_script("s/a/b/g") is True
    assert main.is_safe_sed_script("5d") is True
    assert main.is_safe_sed_script("1,5s/x/y/") is True
    assert main.is_safe_sed_script("2~3p") is True
    assert main.is_safe_sed_script("/re/p") is True
    assert main.is_safe_sed_script("s/a/b/e") is False
    assert main.is_safe_sed_script("y/a/b/") is False


def test_sed_expression_flag():
    assert main.sed_expression_script("--expression=s/a/b/", ["sed", "--expression=s/a/b/", "f"], 1) == ("s/a/b/", 2)
    assert main.is_safe_sed(["sed", "--expression=s/a/b/", "f"]) is True


def test_sed_stdin_only():
    assert main.is_safe_sed_stdin_only(["sed", "s/a/b/"]) is True
    assert main.is_safe_sed_stdin_only(["sed", "s/a/b/", "f"]) is False


def test_sed_in_place_edit_rule():
    edit_deny = [src(deny={"Edit": [f"^{HOME_RE}/\\.ssh/.*$"]})]
    assert main.is_safe_sed_in_place(
        ["sed", "-i", "s/a/b/", f"{HOME}/.ssh/id_rsa"], edit_deny
    ) is False
    assert main.is_safe_sed_in_place(
        ["sed", "-i", "s/a/b/", "/tmp/ok"], edit_deny
    ) is True
    # `..` traversal resolves to the protected path.
    assert main.is_safe_sed_in_place(
        ["sed", "-i", "s/a/b/", f"{HOME}/decoy/../.ssh/id_rsa"], edit_deny
    ) is False


def test_sed_in_place_implicit_pipeline():
    edit_deny = [src(deny={"Edit": [f"^{HOME_RE}/\\.ssh/.*$"]})]
    assert ev(f"sed -i 's/a/b/' {HOME}/.ssh/id_rsa", *edit_deny).decision == "ask"
    assert ev("sed -i 's/a/b/' /tmp/ok", *edit_deny).decision == "allow"


# ---------------------------------------------------------------------------
# 12. awk safety
# ---------------------------------------------------------------------------


def test_awk_safe_forms():
    assert main.is_safe_awk(["awk", "'{print $1}'", "f"]) is True
    assert main.is_safe_awk(["awk", "'NR==FNR'", "a", "b"]) is True
    assert main.is_safe_awk(["awk", "'/foo|bar/'", "f"]) is True
    assert main.is_safe_awk(["awk", "'$3 > 100'", "f"]) is True
    assert main.is_safe_awk(["awk", "'if (x > y)'", "f"]) is True
    assert main.is_safe_awk(["awk", "'$3 >= 100'", "f"]) is True
    assert main.is_safe_awk(["awk", "'$3 <= 100'", "f"]) is True
    assert main.is_safe_awk(["awk", "'print x >= 5'", "f"]) is True
    assert main.is_safe_awk(["awk", "'{print \"a|b\"}'", "f"]) is True


def test_awk_division():
    for prog in ["$2/$1", "1/2", "a++ / 2", "++a / 2", "(a+b)/c", "$0/2", "a[1]/2", '"s"/2', "a /= 2"]:
        assert main.is_safe_awk_program(prog) is True


def test_awk_regex_starts():
    for prog in ["x = /re/", "print /re/", "~ /re/", "//", "/system/"]:
        assert main.is_safe_awk_program(prog) is True


def test_awk_getline_plain():
    assert main.is_safe_awk_program("getline") is True
    assert main.is_safe_awk_program("getline x") is True
    assert main.is_safe_awk_program("while ((getline x) > 0)") is True


def test_awk_flags_and_binaries():
    assert main.is_safe_awk(["awk", "-F:", "'{print $1}'", "f"]) is True
    assert main.is_safe_awk(["awk", "-v", "x=1", "'{print}'", "f"]) is True
    assert main.is_safe_awk(["awk", "-vx=1", "'{print}'", "f"]) is True
    assert main.is_safe_awk(["awk", "--version"]) is True
    assert main.is_safe_awk(["mawk", "'{print}'", "f"]) is True
    assert main.is_safe_awk(["nawk", "'{print}'", "f"]) is True
    assert main.is_safe_awk(["/usr/bin/awk", "'{print}'", "f"]) is True


def test_awk_unsafe_constructs():
    assert main.is_safe_awk_program("system(") is False
    assert main.is_safe_awk_program('"cmd" | getline') is False
    assert main.is_safe_awk_program('print x | "cmd"') is False
    assert main.is_safe_awk_program("print x |& cmd") is False
    assert main.is_safe_awk_program('getline < "f"') is False
    assert main.is_safe_awk_program('while ((getline x < "f") > 0)') is False
    assert main.is_safe_awk_program('getline a[1] < "f"') is False
    assert main.is_safe_awk_program('print x > "f"') is False
    assert main.is_safe_awk_program('print x >> "f"') is False
    assert main.is_safe_awk_program("print x>y") is False
    assert main.is_safe_awk_program('print (a) > "f"') is False
    assert main.is_safe_awk_program('printf("%s",x) > "f"') is False
    assert main.is_safe_awk_program('print a?b:c > "f"') is False
    assert main.is_safe_awk_program('print x \\\n > "f"') is False
    assert main.is_safe_awk_program('"/inet/tcp/0/127.0.0.1/80"') is False
    assert main.is_safe_awk_program("@load") is False
    assert main.is_safe_awk_program("@include") is False
    assert main.is_safe_awk_program('f="system"; @f("id")') is False
    assert main.is_safe_awk_program("SYMTAB") is False
    assert main.is_safe_awk_program("FUNCTAB") is False
    assert main.is_safe_awk_program("dbmopen") is False


def test_awk_unsafe_flags():
    assert main.is_safe_awk(["awk", "-i", "inplace", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-l", "lib", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-E", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-f", "file", "f"]) is False
    assert main.is_safe_awk(["awk", "-W", "compat", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-d", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-p", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-o", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "--profile", "'{print}'", "f"]) is False
    assert main.is_safe_awk(["awk", "-x", "'{print}'", "f"]) is False


def test_awk_no_or_bad_program():
    assert main.is_safe_awk(["awk"]) is False
    assert main.is_safe_awk(["awk", "''"]) is False
    assert main.is_safe_awk(["awk", '"{print}"', "f"]) is False
    assert main.is_safe_awk(["awk", "{print}", "f"]) is False
    assert main.is_safe_awk(["awk", '"$x"', "f"]) is False


def test_awk_unclosed_fail_closed():
    assert main.is_safe_awk_program('{print "unclosed') is False
    assert main.is_safe_awk_program("{print") is False
    assert main.is_safe_awk_program("x = /re") is False
    assert main.is_safe_awk_program("(x") is False
    assert main.is_safe_awk_program("print x }") is False


# ---------------------------------------------------------------------------
# 13. Path-argument checking
# ---------------------------------------------------------------------------


def test_path_arg_credential_deny():
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("cat ~/.ssh/id_rsa", s).decision == "deny"


def test_path_arg_traversal():
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("cat ~/decoy/../.ssh/id_rsa", s).decision == "deny"


def test_path_arg_embedded_quote():
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev(f'cat "{HOME}/.ssh/id_rsa"', s).decision == "deny"


def test_path_arg_read_allow_override():
    cat_allow = src(
        allow={"Bash": ["^cat"], "Read": [f"^{HOME_RE}/\\.ssh/id_rsa$"]}
    )
    cred = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev(f"cat {HOME}/.ssh/id_rsa", cat_allow, cred).decision == "allow"
    assert ev(f"cat {HOME}/.ssh/id_rsa", src(allow={"Bash": ["^cat"]}), cred).decision == "deny"


def test_path_arg_trailing_slash():
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/$"]})
    assert ev(f"cat {HOME}/.ssh", s).decision == "deny"


def test_path_arg_redirect_target():
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    # read-redirect to a credential is caught (was silently allowed).
    assert ev("cat < ~/.ssh/id_rsa", s).decision == "deny"
    assert ev(f"cat < {HOME}/.ssh/config", s).decision == "deny"
    # heredoc delimiter / here-string content are literal strings, not file paths.
    assert ev("cat <<EOF\nhello\nEOF", s).decision == "allow"
    assert ev(f"cat <<< {HOME}/.ssh/id_rsa", s).decision == "allow"


def test_operand_roles_table():
    # Destination-last commands: sources are inputs, the last operand is output.
    assert main._operand_roles("cp", ["a", "b"], None) == [(True, False), (False, True)]
    assert main._operand_roles("install", ["a", "b"], None) == [(True, False), (False, True)]
    assert main._operand_roles("ln", ["a", "b"], None) == [(True, False), (False, True)]
    assert main._operand_roles("rsync", ["a", "b", "c"], None) == [
        (True, False), (True, False), (False, True),
    ]
    # mv sources are read *and* removed; -t moves the destination index.
    assert main._operand_roles("mv", ["a", "b"], None) == [(True, True), (False, True)]
    assert main._operand_roles("mv", ["dest", "src"], 0) == [(False, True), (True, True)]
    # All-output commands (write/create/delete): every operand is output.
    for name in ("rm", "rmdir", "unlink", "truncate", "shred", "mkdir"):
        assert main._operand_roles(name, ["a", "b"], None) == [(False, True), (False, True)], name
    # Output-via-flag commands: the flag value is the output, the rest inputs.
    for name in ("pandoc", "mutool", "yt-dlp", "unzip"):
        assert main._operand_roles(name, ["in", "out"], None) == [(True, False), (True, False)], name
        assert main._operand_roles(name, ["in", "out"], 1) == [(True, False), (False, True)], name
    # First-input-second-output commands.
    assert main._operand_roles("pdftotext", ["in"], None) == [(True, False)]
    assert main._operand_roles("pdftotext", ["in", "out"], None) == [(True, False), (False, True)]
    assert main._operand_roles("tesseract", ["in", "out"], None) == [(True, False), (False, True)]
    # Read-only default, and sed -i flips operands to output.
    assert main._operand_roles("grep", ["a", "b"], None) == [(True, False), (True, False)]
    assert main._operand_roles("sed", ["a"], None) == [(True, False)]
    assert main._operand_roles("sed", ["a"], None, sed_in_place=True) == [(False, True)]


def test_io_path_cp_dest_mutating_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^cp"]}, deny={"Edit": [f"^{HOME_RE}/dest$"]})
    assert ev(f"cp {HOME}/src {HOME}/dest", s).decision == "deny"


def test_io_path_cp_dest_read_deny_noop(monkeypatch):
    # Writing to a path is not reading it: a Read deny on the destination does
    # not block the copy.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^cp"]}, deny={"Read": [f"^{HOME_RE}/dest$"]})
    assert ev(f"cp {HOME}/src {HOME}/dest", s).decision == "allow"


def test_io_path_cp_source_read_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^cp"]}, deny={"Read": [f"^{HOME_RE}/src$"]})
    assert ev(f"cp {HOME}/src {HOME}/dest", s).decision == "deny"


def test_io_path_mv_source_mutating_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^mv"]}, deny={"Edit": [f"^{HOME_RE}/src$"]})
    assert ev(f"mv {HOME}/src {HOME}/dest", s).decision == "deny"


def test_io_path_rm_mutating_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^rm"]}, deny={"Edit": [f"^{HOME_RE}/foo$"]})
    assert ev(f"rm {HOME}/foo", s).decision == "deny"


def test_io_path_rm_read_deny_noop(monkeypatch):
    # Deleting a file is a mutation; a Read deny alone does not block it.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^rm"]}, deny={"Read": [f"^{HOME_RE}/foo$"]})
    assert ev(f"rm {HOME}/foo", s).decision == "allow"


def test_io_path_sed_in_place_mutating_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^sed"]}, deny={"Edit": [f"^{HOME_RE}/foo$"]})
    assert ev(f"sed -i 's/a/b/' {HOME}/foo", s).decision == "deny"


def test_io_path_write_redirect_mutating_deny(monkeypatch):
    # A write redirect to a safe path is governed by mutating rules.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^cat"]}, deny={"Edit": ["^/tmp/out$"]})
    assert ev("cat /etc/hostname > /tmp/out", s).decision == "deny"


def test_io_path_fd_dup_redirect_not_a_path(monkeypatch):
    # Numeric fd dups (`2>&1`, `0<&1`) and fd closes (`>&-`) are file descriptors,
    # not file paths: a broad mutating/read deny must not fire on `/cwd/1`/`/cwd/0`.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    mut = src(allow={"Bash": ["^cat"]}, deny={"Edit": [".*"]})
    assert ev("cat foo 2>&1", mut).decision == "allow"
    assert ev("cat foo 0<&1", mut).decision == "allow"
    echo = src(allow={"Bash": ["^echo"]}, deny={"Edit": [".*"]})
    assert ev("echo hi >&1", echo).decision == "allow"
    assert ev("echo hi >&-", echo).decision == "allow"
    read = src(allow={"Bash": ["^cat"]}, deny={"Read": [".*"]})
    assert ev("cat 0<&1", read).decision == "allow"


def test_io_path_unknown_tool_read_only(monkeypatch):
    # Unknown commands keep the conservative default: operands are inputs (Read).
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    edit = src(allow={"Bash": ["^file"]}, deny={"Edit": [f"^{HOME_RE}/foo$"]})
    read = src(allow={"Bash": ["^file"]}, deny={"Read": [f"^{HOME_RE}/foo$"]})
    assert ev(f"file {HOME}/foo", edit).decision == "allow"
    assert ev(f"file {HOME}/foo", read).decision == "deny"


def test_io_path_mkdir_mutating_deny(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^mkdir"]}, deny={"Edit": [f"^{HOME_RE}/newdir$"]})
    assert ev(f"mkdir {HOME}/newdir", s).decision == "deny"


def test_io_path_mkdir_read_deny_noop(monkeypatch):
    # Creating a directory is a mutation; a Read deny alone does not block it.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^mkdir"]}, deny={"Read": [f"^{HOME_RE}/newdir$"]})
    assert ev(f"mkdir {HOME}/newdir", s).decision == "allow"


def test_io_path_pandoc_output_flag(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    edit = src(allow={"Bash": ["^pandoc"]}, deny={"Edit": [f"^{HOME_RE}/out\\.html$"]})
    read = src(allow={"Bash": ["^pandoc"]}, deny={"Read": [f"^{HOME_RE}/in\\.md$"]})
    # The -o/--output value is the output (mutating); the input is read.
    assert ev(f"pandoc {HOME}/in.md -o {HOME}/out.html", edit).decision == "deny"
    assert ev(f"pandoc {HOME}/in.md --output={HOME}/out.html", edit).decision == "deny"
    assert ev(f"pandoc {HOME}/in.md --output {HOME}/out.html", edit).decision == "deny"
    assert ev(f"pandoc {HOME}/in.md -o {HOME}/out.html", read).decision == "deny"
    # A Read deny on the output does not block (the output is not read).
    ro = src(allow={"Bash": ["^pandoc"]}, deny={"Read": [f"^{HOME_RE}/out\\.html$"]})
    assert ev(f"pandoc {HOME}/in.md -o {HOME}/out.html", ro).decision == "allow"
    assert ev(f"pandoc {HOME}/in.md --output {HOME}/out.html", ro).decision == "allow"


def test_io_path_unzip_directory_flag(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^unzip"]}, deny={"Edit": [f"^{HOME_RE}/extract$"]})
    assert ev(f"unzip {HOME}/a.zip -d {HOME}/extract", s).decision == "deny"


def test_io_path_mutool_output_flag(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^mutool"]}, deny={"Edit": [f"^{HOME_RE}/out\\.pdf$"]})
    assert ev(f"mutool convert -o {HOME}/out.pdf {HOME}/in.pdf", s).decision == "deny"


def test_io_path_pdftotext_second_output(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # Second positional is the output; a lone PDF is read-only.
    edit = src(allow={"Bash": ["^pdftotext"]}, deny={"Edit": [f"^{HOME_RE}/out\\.txt$"]})
    assert ev(f"pdftotext {HOME}/in.pdf {HOME}/out.txt", edit).decision == "deny"
    assert ev(f"pdftotext {HOME}/in.pdf", src(allow={"Bash": ["^pdftotext"]}, deny={"Edit": [f"^{HOME_RE}/in\\.pdf$"]})).decision == "allow"
    assert ev(f"pdftotext {HOME}/in.pdf", src(allow={"Bash": ["^pdftotext"]}, deny={"Read": [f"^{HOME_RE}/in\\.pdf$"]})).decision == "deny"


def test_io_path_tesseract_second_output(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^tesseract"]}, deny={"Edit": [f"^{HOME_RE}/outbase$"]})
    assert ev(f"tesseract {HOME}/in.png {HOME}/outbase", s).decision == "deny"


def test_io_path_yt_dlp_output_flag(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^yt-dlp"]}, deny={"Edit": [f"^{HOME_RE}/dl/vid\\.mp4$"]})
    assert ev(f"yt-dlp -o {HOME}/dl/vid.mp4 https://example.com", s).decision == "deny"


# ---------------------------------------------------------------------------
# 14. Project file ops
# ---------------------------------------------------------------------------

PROJ = f"{HOME}/proj"


def test_project_file_op_inside_outside(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert main.evaluate_project_file_op(["rm", PROJ + "/foo"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(["rm", f"{HOME}/other/foo"], [src()], PROJ) is None
    assert main.evaluate_project_file_op(["rm", PROJ + "/.claude/foo"], [src()], PROJ) is None
    assert main.evaluate_project_file_op(["rm", PROJ + "/.git/foo"], [src()], PROJ) is None


def test_project_file_op_target_dir_forms(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert main.evaluate_project_file_op(["cp", "-t", PROJ + "/d", PROJ + "/a"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(["cp", "-t" + PROJ + "/d", PROJ + "/a"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(["cp", "-rt" + PROJ + "/d", PROJ + "/a"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(
        ["cp", "--target-directory=" + PROJ + "/d", PROJ + "/a"], [src()], PROJ
    ).decision == "allow"


def test_project_file_op_gio_trash(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert main.evaluate_project_file_op(["gio", "trash", PROJ + "/foo"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(["gio", "list", PROJ + "/foo"], [src()], PROJ) is None


def test_project_file_op_policy_wins(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", PROJ)
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert ev("rm " + PROJ + "/foo", src(deny={"Bash": ["^rm"]})).decision == "deny"
    assert ev("rm " + PROJ + "/foo").decision == "allow"


def test_project_file_op_no_project_dir(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert ev("rm " + PROJ + "/foo").decision == "ask"


def test_project_file_op_untracked_asks(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    assert main.evaluate_project_file_op(["rm", PROJ + "/foo"], [src()], PROJ) is None


def test_project_file_op_mutating_allowlist_carves_out_untracked(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        s = src(allow={tool: [f"^{re.escape(PROJ)}/foo$"]})
        assert (
            main.evaluate_project_file_op(["rm", PROJ + "/foo"], [s], PROJ).decision
            == "allow"
        ), tool


def test_project_file_op_read_allowlist_does_not_carve_out(monkeypatch):
    # A Read allow authorizes read-only access, not deletion — the untracked
    # file still falls through to ask.
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    s = src(allow={"Read": [f"^{re.escape(PROJ)}/foo$"]})
    assert main.evaluate_project_file_op(["rm", PROJ + "/foo"], [s], PROJ) is None


def test_project_file_op_allowlist_does_not_cover_other_path(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    s = src(allow={"Edit": [f"^{re.escape(PROJ)}/foo$"]})
    # `foo` is mutating-allow-listed (exempt); `bar` is not -> still asks.
    assert main.evaluate_project_file_op(["rm", PROJ + "/foo", PROJ + "/bar"], [s], PROJ) is None


def test_project_file_op_deny_beats_allowlist(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    s = src(
        allow={"Edit": [f"^{re.escape(PROJ)}/foo$"]},
        deny={"Write": [f"^{re.escape(PROJ)}/foo$"]},
    )
    # rm deletes `foo`, so a mutating (Write) deny beats the Edit allowlist.
    assert main.evaluate_project_file_op(["rm", PROJ + "/foo"], [s], PROJ).decision == "deny"


def test_project_file_op_root_delete_denied(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert main.evaluate_project_file_op(["rm", PROJ], [src()], PROJ).decision == "deny"
    assert main.evaluate_project_file_op(["rmdir", PROJ], [src()], PROJ).decision == "deny"
    assert main.evaluate_project_file_op(["gio", "trash", PROJ], [src()], PROJ).decision == "deny"
    assert main.evaluate_project_file_op(["mv", PROJ, PROJ + "/x"], [src()], PROJ).decision == "deny"
    # cp never removes the project root, so a root operand is not a hard deny
    # (git-tracking is stubbed true here, so it auto-allows rather than asking
    # on the untracked "backup" destination — either way, not a deny).
    assert main.evaluate_project_file_op(["cp", PROJ, PROJ + "/backup"], [src()], PROJ).decision != "deny"


def test_project_file_op_mv_target_dir_dest(monkeypatch):
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    # A -t/--target-directory destination is not a removed source, so moving a
    # file *into* the project root is not a false "project root removal".
    assert main.evaluate_project_file_op(["mv", "-t", PROJ, PROJ + "/a"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(["mv", "-t" + PROJ, PROJ + "/a"], [src()], PROJ).decision == "allow"
    assert main.evaluate_project_file_op(
        ["mv", "--target-directory=" + PROJ, PROJ + "/a"], [src()], PROJ
    ).decision == "allow"
    assert main.evaluate_project_file_op(
        ["mv", "--target-directory", PROJ, PROJ + "/a"], [src()], PROJ
    ).decision == "allow"
    # Destination index is found regardless of where the -t flag sits.
    assert main.evaluate_project_file_op(["mv", PROJ + "/a", "-t", PROJ], [src()], PROJ).decision == "allow"
    # But moving the project root as a -t SOURCE is still a root removal.
    assert main.evaluate_project_file_op(["mv", "-t", PROJ + "/sub", PROJ], [src()], PROJ).decision == "deny"


def test_resolve_path_unit(monkeypatch):
    base = "/work"
    assert main._resolve_path("/abs/path", base) == "/abs/path"
    assert main._resolve_path("/a/./b/../c", base) == "/a/c"
    assert main._resolve_path("~/x", base) == HOME + "/x"
    assert main._resolve_path("foo", base) == "/work/foo"
    assert main._resolve_path("./foo", base) == "/work/foo"
    assert main._resolve_path(".", base) == "/work"
    assert main._resolve_path("..", base) == "/"
    assert main._resolve_path("../foo", base) == "/foo"
    # `~user` is delegated to expanduser (fixes the old literal-relative mis-resolve
    # for users that exist); unknown users fall back to the base dir like before.
    user = os.path.basename(HOME)
    if os.path.expanduser("~" + user) != "~" + user:
        assert main._resolve_path("~" + user + "/x", base) == HOME + "/x"
    # Without base_dir, relative paths resolve against $CLAUDE_PROJECT_DIR.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", base)
    assert main._resolve_path("bar") == "/work/bar"
    # `file:` URLs resolve to the local path they address, so they can't dodge
    # the path guards.
    assert main._resolve_path("file:///etc/shadow", base) == "/etc/shadow"
    assert main._resolve_path("file://localhost/etc/shadow", base) == "/etc/shadow"
    assert main._resolve_path("file:/etc/shadow", base) == "/etc/shadow"
    assert main._resolve_path("file:///etc/sha%64ow", base) == "/etc/shadow"
    assert main._resolve_path("FILE:///etc/shadow", base) == "/etc/shadow"
    # Leading slash runs collapse to one — POSIX treats `/etc` and `//etc` as
    # the same file, so `//` must not evade an anchored deny rule.
    assert main._resolve_path("//etc/shadow", base) == "/etc/shadow"
    assert main._resolve_path("file:////etc/shadow", base) == "/etc/shadow"


def test_extract_path_args_resolves_relative(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    assert main.extract_path_args(["foo", "-flag", "./x", "..", ".", "/abs", "~/y"]) == [
        "/work/foo", "/work/x", "/", "/work", "/abs", HOME + "/y",
    ]


def test_io_path_relative_operand_deny(monkeypatch):
    # Bare relative operands (`.ssh/id_rsa`) resolve against the project dir and
    # are checked, instead of being silently dropped.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", HOME)
    read = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/"]})
    assert ev("cat .ssh/id_rsa", read).decision == "deny"
    edit = src(allow={"Bash": ["^mkdir"]}, deny={"Edit": [f"^{HOME_RE}/\\.ssh/"]})
    assert ev("mkdir .ssh/newdir", edit).decision == "deny"


def test_io_path_relative_redirect_deny(monkeypatch):
    # A relative input-redirect target resolves and is read-checked.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", HOME)
    read = src(allow={"Bash": ["^cat"]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/"]})
    assert ev("cat < .ssh/id_rsa", read).decision == "deny"


def test_io_path_url_operand_not_read_as_path(monkeypatch):
    # A URL operand is not a filesystem path: a fetch whose URL ends in `.env`
    # must not resolve to `<cwd>/https:/…/.env` and hit the `.env` deny.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^yt-dlp"]}, deny={"Read": [r"/?\.env[^/]*$"]})
    assert ev("yt-dlp -o /tmp/v.mp4 https://example.com/.env", s).decision == "allow"


def test_io_path_url_operand_broad_read_deny_noop(monkeypatch):
    # A broad Read deny still must not fire on the URL operand.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^yt-dlp"]}, deny={"Read": [".*"]})
    assert ev("yt-dlp -o /tmp/v.mp4 https://example.com", s).decision == "allow"


def test_io_path_wget_url_env_suffix_not_denied(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^wget"]}, deny={"Read": [r"/?\.env[^/]*$"]})
    assert ev("wget -O /tmp/x https://example.com/.env", s).decision == "allow"


def test_io_path_sed_script_not_a_path(monkeypatch):
    # The sed script (`s/a/b/`) is not a file path: a Read deny on the project
    # dir must not resolve it to `<cwd>/s/a/b/` and deny the command.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    s = src(allow={"Bash": ["^sed"]}, deny={"Read": ["^/work/"]})
    assert ev("sed 's/a/b/' /tmp/f", s).decision == "allow"


def test_io_path_sed_file_still_read_checked(monkeypatch):
    # Skipping the script must not skip the real file operand.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    s = src(allow={"Bash": ["^sed"]}, deny={"Read": ["^/tmp/f$"]})
    assert ev("sed 's/a/b/' /tmp/f", s).decision == "deny"


def test_io_path_awk_program_not_a_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    s = src(allow={"Bash": ["^awk"]}, deny={"Read": ["^/work/"]})
    assert ev("awk '{print $1}' /tmp/f", s).decision == "allow"


def test_io_path_stdin_dash_not_a_path(monkeypatch):
    # `-` is stdin, not a path.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": ["^/work/"]})
    assert ev("cat -", s).decision == "allow"


def test_extract_path_args_skips_url(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work")
    assert main.extract_path_args(["https://example.com", "/abs", "rel"]) == [
        "/abs",
        "/work/rel",
    ]


def test_io_path_file_url_resolved_and_checked(monkeypatch):
    # `file://` is a local path, not a remote URL: it must be resolved and the
    # deny rules applied, not skipped like an http(s) URL.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    for cmd in ("curl file:///etc/shadow", "wget file:///etc/shadow", "yt-dlp file:///etc/shadow"):
        s = src(allow={"Bash": [f"^{cmd.split()[0]}"]}, deny={"Read": ["^/etc/shadow$"]})
        assert ev(cmd, s).decision == "deny", cmd


def test_io_path_file_url_forms_and_encoding(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    deny = {"Read": ["^/etc/shadow$"]}
    for url in ("file://localhost/etc/shadow", "file:/etc/shadow", "file:///etc/sha%64ow", "FILE:///etc/shadow"):
        s = src(allow={"Bash": ["^curl"]}, deny=deny)
        assert ev(f"curl {url}", s).decision == "deny", url


def test_io_path_file_url_output_checked(monkeypatch):
    # A `file://` destination is a write to a local path: it must hit mutating
    # rules, not be skipped as a URL.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^wget"]}, deny={"Write": ["^/etc/shadow$"]})
    assert ev("wget -O file:///etc/shadow https://example.com", s).decision == "deny"


def test_io_path_remote_url_still_skipped(monkeypatch):
    # A remote scheme is still not a path: the `.env`-suffixed http URL is not
    # read-checked, while `file://` to the same path is.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    deny = {"Read": [r"/?\.env[^/]*$"]}
    remote = src(allow={"Bash": ["^curl"]}, deny=deny)
    assert ev("curl https://example.com/.env", remote).decision == "allow"
    local = src(allow={"Bash": ["^curl"]}, deny=deny)
    assert ev("curl file:///etc/.env", local).decision == "deny"


def test_io_path_double_slash_path_checked(monkeypatch):
    # `//etc/shadow` addresses the same file as `/etc/shadow` on POSIX; a
    # leading-slash run must not evade an anchored deny rule.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    s = src(allow={"Bash": ["^cat"]}, deny={"Read": ["^/etc/shadow$"]})
    assert ev("cat //etc/shadow", s).decision == "deny"


def test_project_file_op_relative(monkeypatch):
    # `.`/`..`/bare relative operands resolve against the project dir.
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: True)
    assert main.evaluate_project_file_op(["rm", "."], [src()], PROJ).decision == "deny"
    assert main.evaluate_project_file_op(["rm", ".."], [src()], PROJ) is None
    assert main.evaluate_project_file_op(["rm", "foo"], [src()], PROJ).decision == "allow"
    monkeypatch.setattr(main, "_git_paths_tracked", lambda project_dir, paths: False)
    assert main.evaluate_project_file_op(["rm", "foo"], [src()], PROJ) is None


def test_file_tool_relative_path_resolved(monkeypatch):
    # File-tool paths (`file_path`/`notebook_path`) are resolved before matching,
    # so a relative path hits the same absolute-path rules as an absolute one.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", HOME)
    read = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/"]})
    assert main._eval_non_bash([read], "Read", ".ssh/id_rsa").decision == "deny"
    edit = src(deny={"Edit": [f"^{HOME_RE}/\\.ssh/"]})
    assert main._eval_non_bash([edit], "Edit", ".ssh/new").decision == "deny"


def test_git_paths_tracked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("x")
    (repo / "café.txt").write_text("x")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "ignored.txt").write_text("x")
    (repo / "sub").mkdir()
    (repo / "sub" / "inner.txt").write_text("x")
    subprocess.run(["git", "add", "tracked.txt", "café.txt", ".gitignore", "sub"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo, check=True,
    )
    (repo / "untracked.txt").write_text("x")
    empty = repo / "empty"
    empty.mkdir()

    assert main._git_paths_tracked(str(repo), [str(repo / "tracked.txt")]) is True
    assert main._git_paths_tracked(str(repo), [str(repo / "café.txt")]) is True
    assert main._git_paths_tracked(str(repo), [str(repo)]) is True  # root holds tracked files
    assert main._git_paths_tracked(str(repo), [str(repo / "untracked.txt")]) is False
    assert main._git_paths_tracked(str(repo), [str(repo / "ignored.txt")]) is False
    assert main._git_paths_tracked(str(repo), [str(repo / "sub")]) is True
    assert main._git_paths_tracked(str(repo), [str(empty)]) is False
    assert main._git_paths_tracked(str(tmp_path), [str(tmp_path / "x")]) is False


# ---------------------------------------------------------------------------
# 15. Self-protection guard
# ---------------------------------------------------------------------------


PROTECTED = [
    f"{HOME}/.claude/permissions.json",
    f"{HOME}/.claude/permissions.local.json",
    f"{HOME}/.claude/settings.json",
    f"{HOME}/.claude/settings.local.json",
    f"{HOME}/.claude/hooks/tool-permissions/main.py",
    f"{HOME}/.claude/hooks/tool-permissions/pyproject.toml",
    f"{HOME}/.claude/hooks/tool-permissions/uv.lock",
    f"{HOME}/.claude/hooks/tool-permissions/permissions.schema.json",
    # plugin-installed copy under ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/
    f"{HOME}/.claude/plugins/cache/lena-miyamoto/tool-permissions/0.1.0/hooks/tool-permissions/main.py",
    f"{HOME}/.claude/plugins/cache/lena-miyamoto/tool-permissions/0.1.0/hooks/tool-permissions/pyproject.toml",
    f"{HOME}/.claude/plugins/cache/lena-miyamoto/tool-permissions/0.1.0/hooks/tool-permissions/uv.lock",
    f"{HOME}/.claude/plugins/cache/lena-miyamoto/tool-permissions/0.1.0/hooks/tool-permissions/permissions.schema.json",
]


def test_self_protection_matches():
    for p in PROTECTED:
        assert main.edits_protected_file("Edit", p) is True, p
    # Read is not a mutating tool.
    assert main.edits_protected_file("Read", PROTECTED[0]) is False


def test_self_protection_non_matches():
    assert main.edits_protected_file("Edit", f"{HOME}/.claude/settings.json.bak") is False
    assert main.edits_protected_file("Edit", f"{HOME}/.claude/agent-templates/settings.json") is False


def test_self_protection_allow_to_ask():
    s = [src(allow={"Edit": [f"{HOME_RE}/\\.claude/.*"]})]
    assert main._eval_non_bash(s, "Edit", PROTECTED[2]).decision == "ask"


def test_self_protection_deny_intact():
    s = [src(deny={"Edit": [f"{HOME_RE}/\\.claude/.*"]})]
    assert main._eval_non_bash(s, "Edit", PROTECTED[2]).decision == "deny"


def test_self_protection_bash_redirect_write():
    s = src(allow={"Bash": ["^echo"]})
    r = ev(f"echo hi > {HOME}/.claude/settings.json", s)
    assert r.decision == "ask"


# ---------------------------------------------------------------------------
# 16. Source precedence + expansion
# ---------------------------------------------------------------------------


def test_source_allow_over_deny():
    s = src(allow={"Bash": ["^git"]}, deny={"Bash": ["^git push"]})
    assert ev("git push", s).decision == "allow"


def test_source_higher_wins():
    higher = src(allow={"Bash": ["^git push"]})
    lower = src(deny={"Bash": ["^git push"]})
    assert ev("git push", higher, lower).decision == "allow"
    assert ev("git push", lower, higher).decision == "deny"


def test_expand_grouped_keys():
    assert main.expand_grouped_keys({"Read|Edit|Write": ["p"]}) == {
        "Read": ["p"], "Edit": ["p"], "Write": ["p"],
    }


def test_expand_tilde_bucket():
    home = os.path.expanduser("~")
    assert main.expand_tilde_bucket({"Read": ["^~/\\.ssh/"]}) == {
        "Read": ["^" + home + "/\\.ssh/"],
    }


def test_prioritized_opinion_bucket_order():
    s = src(ask={"Bash": ["^git"]}, deny={"Bash": ["^git push"]})
    # ask > deny within a source, so `git push` matches the broader ask.
    assert main.prioritized_opinion([s], "Bash", "git push").decision == "ask"


def test_read_rule_opinion_two_pass():
    s = src(deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]}, ask={"Read": [f"^{HOME_RE}/ok$"]})
    assert main.read_rule_opinion_for_paths([s], [f"{HOME}/.ssh/x"]).decision == "deny"
    assert main.read_rule_opinion_for_paths([s], [f"{HOME}/ok"]).decision == "ask"


# ---------------------------------------------------------------------------
# 17. WebFetch URL delegation for wget/curl
# ---------------------------------------------------------------------------


ANTHROPIC = "^https://([a-zA-Z0-9-]+\\.)*anthropic\\.com(:\\d+)?(/|$)"
MARXISTS = "^https://www\\.marxists\\.org(/|$)"


def test_web_fetch_wget_stdout_allow():
    s = src(allow={"WebFetch": [MARXISTS]})
    cmd = 'wget -qO- --timeout=60 --user-agent="Mozilla/5.0" "https://www.marxists.org/subject/africa/fanon/index.htm"'
    assert ev(cmd, s).decision == "allow"


def test_web_fetch_curl_allow():
    assert ev("curl https://anthropic.com/docs", src(allow={"WebFetch": [ANTHROPIC]})).decision == "allow"


def test_web_fetch_no_url_ask():
    # no URL -> falls through to the blanket curl/wget ask.
    assert ev("curl x").decision == "ask"


def test_web_fetch_off_list_ask():
    s = src(allow={"WebFetch": [MARXISTS]})
    assert ev("wget https://example.com/", s).decision == "ask"


def test_web_fetch_body_ask():
    s = src(allow={"WebFetch": [ANTHROPIC]})
    assert ev("curl -d 'x' https://anthropic.com", s).decision == "ask"


def test_web_fetch_method_override():
    s = src(allow={"WebFetch": [ANTHROPIC]})
    assert ev("curl -X POST https://anthropic.com", s).decision == "ask"
    assert ev("curl -X GET https://anthropic.com", s).decision == "allow"


def test_web_fetch_output_allowed_path():
    s = src(allow={"WebFetch": [ANTHROPIC]})
    assert ev("wget -O /tmp/x https://anthropic.com", s).decision == "allow"


def test_web_fetch_output_read_deny_noop():
    # Writing the output is not reading it: a Read deny on the output path does
    # not block the fetch (mutating rules govern `-O`/`-o`).
    s = src(allow={"WebFetch": [ANTHROPIC]}, deny={"Read": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("wget -O ~/.ssh/id_rsa https://anthropic.com", s).decision == "allow"
    assert ev("curl -o ~/.ssh/id_rsa https://anthropic.com", s).decision == "allow"


def test_web_fetch_output_mutating_deny():
    # wget/curl output paths are governed by mutating (Edit/Write) rules.
    s = src(allow={"WebFetch": [ANTHROPIC]}, deny={"Edit": [f"^{HOME_RE}/\\.ssh/.*$"]})
    assert ev("wget -O ~/.ssh/id_rsa https://anthropic.com", s).decision == "deny"
    assert ev("curl -o ~/.ssh/id_rsa https://anthropic.com", s).decision == "deny"


def test_web_fetch_curl_remote_name_ask():
    # implicit output path (-O/--remote-name) can't be protected -> ask.
    s = src(allow={"WebFetch": [ANTHROPIC]})
    assert ev("curl -O https://anthropic.com", s).decision == "ask"


def test_web_fetch_webfetch_deny_crosses_over():
    s = src(deny={"WebFetch": ["^https://evil\\.com(/|$)"]})
    assert ev("wget https://evil.com/x", s).decision == "deny"


def test_web_fetch_bash_deny_wins():
    s = src(allow={"WebFetch": [ANTHROPIC]}, deny={"Bash": ["^curl"]})
    assert ev("curl https://anthropic.com", s).decision == "deny"


# ---------------------------------------------------------------------------
# 18. Defaults, WebFetch anchoring, Fetch alias, invalid regex
# ---------------------------------------------------------------------------


def test_defaults_non_bash():
    assert main._eval_non_bash([], "Read", "/x").decision == "allow"
    assert main._eval_non_bash([], "WebSearch", "q").decision == "allow"
    assert main._eval_non_bash([], "WebFetch", "u").decision == "allow"
    # tool with a non-empty allow-list that doesn't match -> ask
    assert main._eval_non_bash([src(allow={"Skill": ["x"]})], "Skill", "y").decision == "ask"


def test_webfetch_anchoring():
    wf = [src(allow={"WebFetch": ["^https://([a-zA-Z0-9-]+\\.)*anthropic\\.com(:\\d+)?(/|$)"]})]
    assert main._eval_non_bash(wf, "WebFetch", "https://anthropic.com/docs").decision == "allow"
    # spoofed suffix / userinfo are rejected -> restricted default ask
    assert main._eval_non_bash(wf, "WebFetch", "https://anthropic.com.evil.com").decision == "ask"
    assert main._eval_non_bash(wf, "WebFetch", "https://anthropic.com@evil.com").decision == "ask"


def test_fetch_alias(capsys):
    wf = [src(allow={"WebFetch": ["^https://([a-zA-Z0-9-]+\\.)*anthropic\\.com(:\\d+)?(/|$)"]})]
    assert decide_decision(capsys, wf, "Fetch", {"url": "https://anthropic.com/docs"}) == "allow"
    assert decide_decision(capsys, wf, "Fetch", {"url": "https://anthropic.com.evil.com"}) == "ask"


def test_invalid_regex_warns(capsys):
    assert main.test_pattern("(", "anything") is False
    assert "invalid regex" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 19. End-to-end decide() against the real global policy
# ---------------------------------------------------------------------------


@pytest.fixture
def global_sources(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return main.load_permissions()


def test_e2e_git_status_allow(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "git status"}) == "allow"


def test_e2e_git_push_ask(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "git push"}) == "ask"


def test_e2e_rm_rf_ask(capsys, global_sources):
    # no `rm` deny rule -> default Bash ask (plan's "deny" note is stale).
    assert decide_decision(capsys, global_sources, "Bash", {"command": "rm -rf ~"}) == "ask"


def test_e2e_npm_install_deny(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "npm install"}) == "deny"


def test_e2e_sed_allow(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "sed 's/a/b/' f"}) == "allow"


def test_e2e_awk_allow(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "awk '{print $1}' f"}) == "allow"


def test_e2e_awk_system_ask(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "awk 'BEGIN{system(\"id\")}'"}) == "ask"


def test_e2e_awk_redirect_ask(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "awk '{print $1 > \"out\"}'"}) == "ask"


def test_e2e_gawk_inplace_ask(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "gawk -i inplace '{print}' f"}) == "ask"


def test_e2e_gawk_print_allow(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "gawk '{print}'"}) == "allow"


def test_e2e_curl_ask(capsys, global_sources):
    assert decide_decision(capsys, global_sources, "Bash", {"command": "curl x"}) == "ask"


def test_e2e_curl_webfetch_allowed(capsys, global_sources):
    # anthropic.com is WebFetch-allowed in the global policy, so a plain curl
    # fetch of it is auto-allowed despite the blanket curl ask rule.
    assert decide_decision(capsys, global_sources, "Bash", {"command": "curl https://anthropic.com/docs"}) == "allow"


def test_e2e_uv_run_sync_ask(capsys, global_sources):
    # `uv run`/`uv sync` moved to the ask bucket (can exec arbitrary code), so they prompt.
    assert decide_decision(capsys, global_sources, "Bash", {"command": "uv run pytest"}) == "ask"
    assert decide_decision(capsys, global_sources, "Bash", {"command": "uv sync"}) == "ask"


def test_e2e_uv_install_deny(capsys, global_sources):
    # the remaining `uv` subcommands stay deny-listed.
    assert decide_decision(capsys, global_sources, "Bash", {"command": "uv add requests"}) == "deny"
    assert decide_decision(capsys, global_sources, "Bash", {"command": "uv pip install requests"}) == "deny"


def test_e2e_for_ssh_glob_deny(capsys, global_sources):
    assert decide_decision(
        capsys, global_sources, "Bash", {"command": "for f in ~/.ssh/*; do cat $f; done"}
    ) == "deny"
