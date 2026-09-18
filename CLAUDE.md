# CLAUDE.md

## Confidential data — hard rule

Never write confidential data to any version-controlled file: credit card numbers, bank/giro account numbers (e.g. `AT44…` IBANs), credentials, API keys, other secrets. Repo is public on GitHub — leaking such data is dangerous, **MUST NOT HAPPEN UNDER ANY CIRCUMSTANCES**.

Never send such data directly to the AI model. CLI tools or Python scripts processing it must redact, mask, or omit so it never reaches model context — do not print, paste, or pass it through.

Before committing, verify no confidential values added to tracked files.

## Shared

- Smallest local change that works; stale patch context → re-read exact snippet, retry.
- Re-read current script before every edit, trust file state not memory, validate immediately after each change.
- Preserve existing CLI shape unless user explicitly asks to redesign: flags, env vars, prompts, exit behavior, default side effects are part of the interface.
- Prefer focused validation — `bash -n`, `shellcheck` if available, narrow `--help`/dry-run check — over broad install-script execution.
- Do not run destructive scripts or commands without explicit user intent.
- Shell scripts: keep current style and existing helper abstractions; don't inline one-off logic.
- German prose or user-facing text: standard German orthography with umlauts and `ß` unless user explicitly asks for ASCII.
- File names use kebab-case (`install-statusline.py`), not snake_case. Hyphenated Python scripts are loaded via `importlib`/`runpy`, never `import`ed by name.

## Setup Scripts

- Prefer editing existing helper functions and feature-specific installers over ad hoc logic in the top-level main flow.
- Keep setup actions idempotent — don't regress safe re-runs.
- Preserve the general-setup vs Lena-specific-opt-in split unless user explicitly asks to redesign.
- Download-and-run flows: keep checksum verification; don't weaken integrity checks or silently swap for trust-on-first-use.
- Podman-managed services: preserve the existing safety pattern unless user explicitly asks to expose services.
- Preserve backup/append-only reconfiguration behavior unless user asked for reset.

## Standalone Utilities

- Keep standalone scripts single-purpose, lightweight. Avoid large framework dependencies when standard shell or small scripting-library solutions suffice.
- Preserve safety prompts and obviousness for destructive or privacy-related scripts.
- Converters, scrapers, text-processing utilities: prefer deterministic input/output over cleverness.
- Utility with narrow platform assumption baked in → don't silently broaden or change it without user request.
