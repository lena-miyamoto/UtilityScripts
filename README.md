# Utility Scripts Collection

Personal collection of shell scripts, Python tools, and configuration files accumulated over the years — everything from provisioning a fresh Ubuntu workstation to scraping language-learning resources off the web.

## Claude Code marketplace

This repo doubles as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces). It publishes the [`tool-permissions`](plugins/utility-scripts/hooks/tool-permissions/README.md) `PreToolUse` hook as the `tool-permissions` plugin:

```bash
claude plugin marketplace add lena-miyamoto/UtilityScripts
claude plugin install tool-permissions@lena-miyamoto
```

The hook enforces a regex-based allow/ask/deny policy (schema and a full example in [`agent-templates/claude-global/permissions.json`](agent-templates/claude-global/permissions.json)) on every tool call. It requires Python 3.13+ and `uv`; on first use `uv run` provisions the virtualenv and downloads `rable` automatically. The marketplace manifest lives in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json).

The [`statusline`](plugins/statusline/README.md) plugin ships the custom Claude Code statusline as stdlib-only Python run through `uv` — the main bottom bar (model, context bar, git branch/worktree, vim mode, rate limits, cost) plus a per-row `subagentStatusLine`. Both bars are wired into `~/.claude/settings.json` by the bundled `install-statusline` skill (a plugin cannot enable the main `statusLine` declaratively).

```bash
claude plugin install statusline@lena-miyamoto
```

## Highlights

**[`ubuntu-setup.sh`](ubuntu-setup.sh)** is the centerpiece. It can take a fresh Ubuntu 24.04 or 26.04 install from stock desktop to a fully configured development and gaming environment in one shot. Two main modes:

- `--basic-setup` — the essentials (CLI tools, fonts, Flatpak, snap packages, dev toolchains)
- `--lenas-setup` — everything in `--basic-setup` plus Godot, Java/Gradle, and other personal preferences

What both modes set up: Flatpak + Flatseal, GNOME Shell preferences, essential CLI tools (curl, jq, rhash, ffmpeg, imagemagick, fish, yt-dlp, eza, bat, difftastic, fd, ripgrep, fzf), system utilities (File Roller, GParted), multimedia codecs, MS Core + proprietary fonts, snap apps (Discord, Spotify, Thunderbird), Firefox ESR (apt, replaces the snap build), Flatpak apps (VLC, Cine, GIMP, Inkscape), Tor Browser, Steam + ProtonUp-Qt, dev toolchains (Python via uv, Rust via rustup, Node via fnm, VS Code), the UFW firewall, and the recommended graphics drivers. All downloads are checksum-verified.

`--lenas-setup` additionally sets up: KeePassXC, Brave/Edge/Signal, Veracrypt, Podman, gaming launchers and emulators (Heroic, Azahar, Mupen64Plus), custom fonts, Blender + Element, Java/Gradle, and Godot.

Standalone flags — mutually exclusive with the two modes — cover the rest: `--install-local-ai` (local LLM stack), `--install-godot`, `--install-openssh-server`, plus the `--configure-*` and `--reconfigure-*` maintenance flags. See [Quick start](#quick-start--ubuntu-setup) for the full list.

## Setup & system scripts

| Script                                               | What it does                                                                                        |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| [`ubuntu-setup.sh`](ubuntu-setup.sh)                 | Full Ubuntu workstation provisioning                                                                |
| [`manjaro-setup`](manjaro-setup)                     | Older Manjaro Linux setup script (pacman-based, less comprehensive)                                 |
| [`install-ollama.sh`](install-ollama.sh)             | Standalone Ollama + OpenCode + Claude Code installer configured for local Qwen 2.5 Coder            |
| [`clean-home.sh`](clean-home.sh)                     | Nuclear home directory cleanup — prompts for confirmation, preserves critical dotfiles and XDG dirs |
| [`untrace.sh`](untrace.sh)                           | Linux: clear file-access traces (thumbnail cache, recently-used.xbel)                               |
| [`untrace.bat`](untrace.bat)                         | Windows: clear Explorer file-access history                                                         |
| [`vscode-file-history.mjs`](vscode-file-history.mjs) | Restore files from VS Code's local history into a `restored/` directory                             |

## Language learning tools

Python scripts for building annotated vocabulary lists across Spanish, English, and German.

| Script                                 | What it does                                                                                                                        |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| [`wordanalyzer.py`](wordanalyzer.py)   | Original monolithic analyzer — CSV parsing, dictionary lookups, IPA transcription, verb conjugation, duplicate/new-word detection   |
| [`wordanalyzer/`](wordanalyzer/)       | Refactored modular version — `arguments.py`, `translators.py`, `utils.py`, `wordanalyzer.py`, plus large Spanish/English word lists |
| [`vocabdiff.py`](vocabdiff.py)         | Diff two CSV vocab lists — output rows new to the second file                                                                       |
| [`latincheck.py`](latincheck.py)       | Validate modified Latin vocabulary CSV against an original                                                                          |
| [`russ.py`](russ.py)                   | Parse custom Russian vocabulary text format into CSV                                                                                |
| [`csv-converter.py`](csv-converter.py) | Convert two-line-per-entry CSV to proper semicolon-separated format                                                                 |
| [`csvreader.py`](csvreader.py)         | Minimal educational CSV parser class                                                                                                |
| [`omitlines.py`](omitlines.py)         | Print every Nth line from a text file                                                                                               |

Dictionaries scraped: SpanishDict, DixOsola (ES↔DE, ES↔EN), dict.cc, German/English Wiktionary, Oxford Dictionary.

## Finance tools

Python scripts for parsing bank account CSV exports (easybank, Sparkasse) and grouping expenses into categories.

| Script                                                                     | What it does                                                                                                                                                   |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`finance-tools/parse-kontoauszug.py`](finance-tools/parse-kontoauszug.py) | Parse easybank (Girokonto, Kreditkarte) and Sparkasse CSV exports, categorize expenses by regex, print monthly totals/averages and list unrecognized merchants |
| [`finance-tools/categories.py`](finance-tools/categories.py)               | Category definitions — regex patterns mapped to categories (groceries, restaurants, medical, …) plus the ordered category list and fallback                    |

## Web & media tools

| Script                                                               | What it does                                                                                       |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [`wikicommons-dl.py`](wikicommons-dl.py)                             | Download Japanese character stroke-order images from Wikimedia Commons (hiragana, katakana, kanji) |
| [`wiki-parsers/wikipedia-maps.py`](wiki-parsers/wikipedia-maps.py)   | Download SVG/PNG maps of Japanese prefectures from Wikipedia                                       |
| [`srttools`](srttools)                                               | Manipulate SRT subtitle files — shift times forward/back, stretch end times                        |
| [`webp2gif`](webp2gif)                                               | Convert animated WebP to GIF                                                                       |
| [`webp2png`](webp2png)                                               | Convert WebP to PNG (or animated APNG for multi-frame images)                                      |
| [`fetch-instagram-post.snippet.js`](fetch-instagram-post.snippet.js) | Browser snippet — auto-advance Instagram slideshows, log image URLs                                |

## Quick start — Ubuntu setup

```bash
# Clone and run
git clone https://github.com/lena-miyamoto/UtilityScripts.git
cd UtilityScripts

# Generic: core tooling and apps
./ubuntu-setup.sh --basic-setup

# Full: adds Godot, Java/Gradle, and personal tweaks
./ubuntu-setup.sh --lenas-setup
```

The script is designed to be idempotent and safe to re-run.

### Options

| Flag                          | Effect                                                                                  |
| ----------------------------- | --------------------------------------------------------------------------------------- |
| `-h`, `--help`                | Print help text and exit                                                                |
| `--basic-setup`               | Full install — essentials only                                                          |
| `--lenas-setup`               | Full install — everything in `--basic-setup` plus Godot, Java/Gradle, and Lena's extras |
| `--install-local-ai`          | Local LLM stack (Node.js + Claude Code)                                                 |
| `--install-godot`             | Godot 4.5 via Friendly Godot Version Manager (fgvm)                                     |
| `--install-openssh-server`    | OpenSSH Server container for local testing (requires Podman 5)                          |
| `--configure-gsettings`       | Apply the GNOME settings                                                                |
| `--configure-lenas-gsettings` | Same, plus Lena's private extra settings                                                |
| `--reconfigure-git`           | Reset `~/.gitconfig` and rebuild it from scratch                                        |
| `--reconfigure-lenas-git`     | Same, plus Lena's private extra settings                                                |
| `--reconfigure-vscode`        | Reset the VS Code config and rebuild it from scratch                                    |
| `--reconfigure-lenas-vscode`  | Same, plus Lena's private extra settings                                                |

`--basic-setup` and `--lenas-setup` are mutually exclusive. Each standalone `--install-*` flag is mutually exclusive with both modes, but combinable with the `--configure-*` / `--reconfigure-*` flags. `--install-openssh-server` also requires an existing `~/.ssh/id_ed25519.pub`.

## License

[WTFPL](LICENSE.txt) — Do What The Fuck You Want To Public License v3.
