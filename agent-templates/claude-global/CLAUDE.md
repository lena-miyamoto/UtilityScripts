# Global config

**Below = overrides only. Hard rules always win.**

## NEVER read `~/.claude/settings.json` (auth-token leak)

Holds `env.ANTHROPIC_AUTH_TOKEN`. Never dump it, whole or partial — every tool, every agent, no exception.

- Need one setting? Project the key, never the file: `jq -r '.env.ANTHROPIC_AUTH_TOKEN | if . then "set" else "unset" end' ~/.claude/settings.json`. Key _names_ fine: `jq -r 'paths(scalars) | join(".")' ~/.claude/settings.json`.
- Never delegate the read to a subagent, paste the file into a prompt or agent brief, or write the value to a file, log, PR body, or issue.
- **If it leaks anyway** → say so same turn, name the key, recommend rotating at provider. Never re-read.

## Hard rules

- **Bash templates first, always.** Ad-hoc logic → Bash pipeline of CLI tools, not inline interpreter (`python3 -c`, `node -e`, `perl -e`, throwaway files) — hook auto-evaluates Bash; interpreter body opaque, forces review. Python/Node only when Bash can't express it.
- **Write redirects: literal safe path, not a variable.** Hook parses statically — can't resolve `$VAR` in `> "$BODY"` / `>> "$BODY"`; variable target = write-op escape, forces prompt even for allow-listed `awk`/`printf`. Use literal path hook sees as safe (`/dev/null`, `/tmp/…`).
- `WebFetch` fails → retry with `wget`/`curl`, prefer `wget` if available.
- Never invoke tools by absolute path (`/usr/local/bin/uv`). Always use bare command, rely on `PATH` (`uv`).
- No force-push `main`/`master`/shared branches, no `--no-verify`, no amend pushed commits.
- Verify real app before claiming fix works. Cannot run → say so, not fake success.
- `~/` = home dir (`$HOME` on macOS/Linux, `%USERPROFILE%` on Windows). Resolve to absolute path — never pass `~/...` to any tool.
- **Never print the environment to model context.** `env`, `export -p`, `printenv`, `set`, `declare -p` dump secrets (`ANTHROPIC_AUTH_TOKEN`, tokens).
  - Probe scrubbed instead: `env -i`, `env -u VAR`, or controlled value (`X=1; export -p X`).
  - Redact output (`grep -E '^VAR='`, `sed 's/=.*/=<redacted>/'`, `wc -l`), never dump.
- **Never stage, unstage, commit, or push** unless explicitly demanded or allowed. Applies to skills and sub-agents too. Not asked → leave index and history untouched, report changes instead (preserves user's staged vs. unstaged diff boundary).
- Never hand-pad markdown table cells to align columns; use static tooling if realignment is needed.

## Communication

- Push back with reasoning when wrong. Name tradeoff. No defer without evidence.

### Style

- **Technical terms, jargon**: exact. Never paraphrase `lru_cache`, `SIGTERM`, `O(n²)`, API names, error strings, CLI flags, library names.
- **Surrounding prose**: simple English, short sentences. No idioms or advanced vocabulary.
- **Density**: high. Bullets for multi-part analysis. No filler, no hedging, no pleasantries.
- **No self-praise**: never compliment own output.

## Workflow

- **Reproduce first**: failing test, repro script, UI steps. No fix without repro unless trivial.
- **Deictic references** ("this file", "this script", "in here", etc.) → IDE's active file, passed per prompt.
- **Ambiguous intent** where wrong guess wastes work → `AskUserQuestion` first. Batch independent questions in one call.
- **Large features** → interview via `AskUserQuestion` before code.
- **Multi-file / unfamiliar / unclear scope** → Plan mode. Skip for one-line fixes, read-only work, single-purpose scripts, mechanical renames.
- **Sub-agents: sequential default.** Fan out only if simultaneous read/edit needed _and_ wait worth token cost. Eval model per task, prefer smaller unless justified.
- **Sub-agent caps (max running at once, per model):** Opus 1, Fable 1, Sonnet 3, Haiku 9. Never exceed.
- **Between unrelated tasks** → prefer `/clear` over context pileup.
- **Mandatory skill procedure completion.** Post-work steps (docs, cleanup, compression, profile updates) mandatory, not optional. Skill incomplete until every SKILL.md step done.

## Git and commits

- Conventional Commits subject, ≤80 chars. Body only when _why_ not obvious from diff.
- **No `Co-Authored-By: Claude ...` trailer by default.** Add only when explicitly asked.

### Branch and worktree discipline

- **Never create worktree or switch branches without asking.** Working directory differs from user's view — changes vanish. Applies to `EnterWorktree`, `git worktree add`, `git checkout`, `git switch`, any branch/directory change.
- **Operate on the current branch.** For long-running or isolated tasks (including sub-agents), default to `cwd`; explain why and ask before using `worktree` isolation.
- **If you entered worktree without asking** → exit immediately (`ExitWorktree`, `action: remove`, `discard_changes: true`), re-apply changes to main branch.

## Date and time

- `currentDate` in system prompt = **server time**, not user's local time. Never assume they match.
- Local date/time → `date` and `date -u`. UTC only → `date -u +%Y-%m-%dT%H:%M:%SZ` or `date -u +%s`.

## CLI tools

- **Use `gio trash` over `rm`/`rmdir` if available** (`command -v gio`) — recoverable (`gio list trash://`); fall back to `rm`. Exception: always use `rm`/`rmdir` under `/tmp`.
- No `sed` forms that execute commands or touch files beyond operands: `e`, `w`/`W`, `r`/`R`, `s///e`, `s///w`, `-f`/`--file`.
  - Safe: `-i`/`--in-place`, `s///` (flags `g p i I m M`, digits), `p P d D =`, with `-n -E -r -s -z -u`.
- Prefer if installed: `jq`/`yq`/`xq` (JSON/YAML/XML over `sed`/`awk`), `difft` (structural diff for refactors). `ast-grep`/`sg`: read forms (`run`, `scan`, `test`) pre-allowed; write forms (`-U`, `--update-all`, `new`) ask first.
