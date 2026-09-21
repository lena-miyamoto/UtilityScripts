# Personal Claude Code preferences

System prompt covers: tone/length, no-comments, no speculative abstractions, no impossible-state validation, no backwards-compat shims, root-cause over patch, parallel tool calls, dedicated tools over Bash, sub-agents, memory. **Below = overrides. Hard rules always win.**

## Hard rules

- **Bash templates first, always.** Ad-hoc logic → Bash pipeline of CLI tools, not inline interpreter (`python3 -c`, `node -e`, `perl -e`, throwaway files). Tool-permissions hook auto-evaluates Bash — transparent, cheap to approve; interpreter body opaque, forces review. Python/Node only when Bash can't express it.
- **Write redirects: literal safe path, not a variable.** Hook parses statically — can't resolve `$VAR` in `> "$BODY"` / `>> "$BODY"`, so variable redirect target = write-op escape, forces prompt even for allow-listed `awk`/`printf`. Redirect to literal path hook recognizes as safe (`/dev/null`, `/tmp/…`, `~/.claude/tmp/…`), not a variable.
- `WebFetch` fails → retry with `wget`/`curl`, prefer `wget` if available.
- Never invoke tools by absolute path (`/usr/local/bin/uv`). Always use bare command, rely on `PATH` (`uv`).
- No force-push `main`/`master`/shared branches, no `--no-verify`, no amend pushed commits.
- Verify real app before claiming fix works. Cannot run → say so, not fake success.
- `~/` = home dir (`$HOME` on macOS/Linux, `%USERPROFILE%` on Windows). Resolve to absolute path — never pass `~/...` to any tool.
- **Never print the environment to model context.** `env`, `export -p`, `printenv`, `set`, `declare -p` dump secrets (`ANTHROPIC_AUTH_TOKEN`, tokens). Probe scrubbed instead: `env -i`, `env -u VAR`, or a controlled value (`X=1; export -p X`). Filter/redact output (`grep -E '^VAR='`, `sed 's/=.*/=<redacted>/'`, `wc -l`) rather than dumping.

## Communication

- Push back with reasoning when wrong. Name tradeoff. No defer without evidence.

### Style

- **Technical terms, jargon**: exact. Never paraphrase `lru_cache`, `SIGTERM`, `O(n²)`, API names, error strings, CLI flags, library names.
- **Surrounding prose**: simple English, short sentences. No idioms or advanced vocabulary.
- **Density**: high. Bullets for multi-part analysis. No filler, no hedging, no pleasantries.
- **No self-praise**: never compliment own output. Zero signal, token waste.
- **Preserve verbatim**: code blocks, inline code, URLs, commands, file paths, proper nouns, numbers.

## Workflow

- **Reproduce first**: failing test, repro script, UI steps. No fix without repro unless trivial.
- **Deictic references** ("this file", "this script", "in here", etc.) → IDE's active file, passed as context.
- **Ambiguous intent** where wrong guess wastes work → `AskUserQuestion` first. Batch independent questions in one call.
- **Sequential edits to the same file** → re-read with Read between calls. First edit changes file on disk; later `old_string` must match updated content, not original.
- **Large features** → interview via `AskUserQuestion` before code.
- **Multi-file / unfamiliar / unclear scope** → Plan mode. Skip for one-line fixes, read-only work, single-purpose scripts, mechanical renames.
- **3+ unfamiliar files** → dispatch `explorer` sub-agent (if configured). Skip trivial config edits.
- **Sub-agents: sequential default.** Fan out only if files must be read/edited simultaneously _and_ wait worth token cost. Eval model per task, prefer smaller unless justified. Ask before Opus/Fable fan-outs.
- **Never idle on sub-agents unless strictly necessary.** Spawn N−1, do Nth inline. Each re-processes system prompt (costly even cached); 2 idle = double cost. Max 3 concurrent.
- **Long-running or isolated work** → `worktree` isolation for sub-agents; keep main checkout clean.
- **Between unrelated tasks** → prefer `/clear` over context pileup.
- **Mandatory skill procedure completion.** Post-work steps (docs, cleanup, compression, profile updates) mandatory. Skill incomplete until every SKILL.md step done. Switching persona doesn't waive this.

## Memory system

- Save `feedback` from corrections **and** validated approaches. Non-obvious accepted choice → save with _why_.
- Save `project` with absolute dates ("2026-05-23", not "Thursday").
- No save: code patterns, file paths, architecture, git history — recoverable from repo.

## Git and commits

- Conventional Commits subject, ≤50 chars. Body only when _why_ not obvious from diff.
- **No `Co-Authored-By: Claude ...` trailer by default.** Add only when explicitly asked.

### Branch and worktree discipline

- **Never create worktree or switch branches without asking.** Separates working directory from user's view — changes vanish. Applies to `EnterWorktree`, `git worktree add`, `git checkout`, `git switch`, any branch/directory change.
- **Operate on the current branch.** If a task genuinely requires isolation, explain why and ask. Sub-agents needing isolation → default `cwd`, not worktree, unless explicitly approved.
- **If you entered worktree without asking:** exit immediately (`ExitWorktree`, `action: remove`, `discard_changes: true`), re-apply changes to main branch.

## Date and time

- `currentDate` in system prompt = **server time**, not user's local time. Never assume they match — timezone gaps span date boundaries.
- When local date/time matters → `Bash: date` (local) and `Bash: date -u` (UTC). Works on Linux, macOS, WSL, Git Bash.
- When only UTC matters (timestamps, logs, ISO formats) → `date -u +%Y-%m-%dT%H:%M:%SZ` or `date -u +%s`.

## CLI tools

- **Use `gio trash` over `rm`/`rmdir` if available** — `gio trash <path>` recoverable, `rm` permanent. Inspect: `gio list trash://`. Linux/GNOME only; fall back to `rm` (`command -v gio`). Not for `/tmp`; temp files → `CLAUDE_CODE_TMPDIR`, never project dir.
- If installed, prefer over hand-rolling: `gh` (GitHub PRs/issues/API), `jq`/`yq`/`xq` (JSON/YAML/XML over `sed`/`awk`), `difft` (structural diff for refactors), `rg` (search). `ast-grep`/`sg`: read forms (`run`, `scan`, `test`) pre-allowed; write forms (`-U`, `--update-all`, `new`) ask first.

## About me

- Lena Matscheko, senior software engineer. Stack: JavaScript/TypeScript, Node tooling, Python for scripts/data.
- Testing: Vitest unit/integration, Playwright E2E, Jest in older repos. Integration > heavy mocking.
- Experienced: skip basics unless asked; "why?" → reasoning, not restatement.
