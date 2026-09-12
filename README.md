# Utility Scripts Collection

Personal collection of shell scripts, Python tools, and configuration files accumulated over the years — everything from provisioning a fresh Ubuntu workstation to scraping language-learning resources off the web.

## Claude Code marketplace

This repo doubles as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces). It publishes the [`tool-permissions`](plugins/utility-scripts/hooks/tool-permissions/README.md) `PreToolUse` hook as the `tool-permissions` plugin:

```bash
claude plugin marketplace add lena-miyamoto/UtilityScripts
claude plugin install tool-permissions@lena-miyamoto
```

The hook enforces a regex-based allow/ask/deny policy (schema and a full example in [`agent-templates/claude-global/permissions.json`](agent-templates/claude-global/permissions.json)) on every tool call. It requires Python 3.13+ and `uv`; on first use `uv run` provisions the virtualenv and downloads `rable` automatically.

## Highlights

**[`ubuntu-setup.sh`](ubuntu-setup.sh)** is the centerpiece. It can take a fresh Ubuntu 24.04 or 26.04 install from stock desktop to a fully configured development and gaming environment in one shot. Two modes:

- `--basic-setup` — the essentials (CLI tools, fonts, Flatpak, snap packages, dev toolchains)
- `--lenas-setup` — adds Godot, Android SDK, and other personal preferences

What it sets up: Flatpak + Flatseal, GNOME Shell preferences, essential CLI tools (curl, jq, rhash, ffmpeg, imagemagick, fish, yt-dlp, eza, bat, difftastic, fd, ripgrep, fzf), system utilities (KeePassXC, File Roller, GParted), multimedia codecs, fonts (MS Core, custom), Snap apps (Discord, Spotify, Thunderbird), Flatpak apps (VLC, GIMP, Inkscape, Blender, Element, Heroic, ProtonUp-Qt, emulators), browsers (Brave, Edge, Tor), dev toolchains (Python via uv, Rust via rustup, Node via fnm, Java/Gradle), VS Code, local LLM stack (llama.cpp/Ollama, OpenCode, Claude Code), and containerized services via Podman (Open WebUI, Gitea, OpenSSH server). All downloads are checksum-verified.

## Setup & system scripts

| Script                                               | What it does                                                                                        |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| [`ubuntu-setup.sh`](ubuntu-setup.sh)                 | Full Ubuntu workstation provisioning (~1784 lines)                                                  |
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

## Web & media tools

| Script                                                               | What it does                                                                                       |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [`wikicommons-dl.py`](wikicommons-dl.py)                             | Download Japanese character stroke-order images from Wikimedia Commons (hiragana, katakana, kanji) |
| [`wiki-parsers/wikipedia-maps.py`](wiki-parsers/wikipedia-maps.py)   | Download SVG/PNG maps of Japanese prefectures from Wikipedia                                       |
| [`srttools`](srttools)                                               | Manipulate SRT subtitle files — shift times forward/back, stretch end times                        |
| [`webp2gif`](webp2gif)                                               | Convert animated WebP to GIF                                                                       |
| [`webp2png`](webp2png)                                               | Convert WebP to PNG (or animated APNG for multi-frame images)                                      |
| [`fetch-instagram-post.snippet.js`](fetch-instagram-post.snippet.js) | Browser snippet — auto-advance Instagram slideshows, log image URLs                                |

## Other files

| File                                   | Description                                                                         |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| [`autoexec.cfg`](autoexec.cfg)         | CS:GO config — keybinds, crosshair, video/net settings, HUD                         |
| [`agent-templates/`](agent-templates/) | GitHub Copilot instruction templates (global prefs + custom explorer agent)         |
| [`.vscode/`](.vscode/)                 | VS Code workspace settings — extensions, formatters, Claude Code terminal allowlist |
| [`.editorconfig`](.editorconfig)       | UTF-8, LF, 2-space indent, 100-char lines                                           |

## Quick start — Ubuntu setup

```bash
# Clone and run
git clone https://github.com/lena-miyamoto/UtilityScripts.git
cd UtilityScripts

# Generic: core tooling and apps
./ubuntu-setup.sh --basic-setup

# Full: adds Godot, Android SDK, and personal tweaks
./ubuntu-setup.sh --lenas-setup
```

The script is designed to be idempotent and safe to re-run.

## License

[WTFPL](LICENSE.txt) — Do What The Fuck You Want To Public License v3.
