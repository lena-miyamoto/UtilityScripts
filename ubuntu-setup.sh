#!/bin/bash
IFS=$'\n\t'
set -euo pipefail
shopt -s globstar nullglob

SCRIPT_DIR="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"

function downloadAndVerify() {
  local url=${1:-}
  local fileName=${2:-}
  local controlHash=${3:-}
  local useTempFile=${4:-}

  local downloadFile
  local fileHash

  if ! command -v wget &>/dev/null; then
    sudo apt install -y wget
  fi
  if ! command -v rhash &>/dev/null; then
    sudo apt install -y rhash
  fi

  if [[ "$useTempFile" == "true" ]]; then
    downloadFile=$(mktemp --suffix=".$fileName")

    # TODO ensure file cleanup on exit (currently throws an odd error)
    # trap 'rm -f -- "$downloadFile"' EXIT
  else
    downloadFile="$HOME/Downloads/$fileName"
  fi

  if [[ "$useTempFile" != "true" ]] && [ -f "$downloadFile" ]; then
    echo "File '$downloadFile' already exists. Skip download."
  else
    echo "Downloading '$url' to '$downloadFile'..."
    wget -q --show-progress "$url" -O "$downloadFile"
  fi

  fileHash=$(rhash --sha512 "$downloadFile" | grep -oE '^\w+')

  if [[ "$fileHash" == "$controlHash" ]]; then
    echo "File hash matches ($url --> $downloadFile)! [sha512.$fileHash]"
    UBUNTU_SETUP_LAST_DOWNLOADED_FILE=$downloadFile
  else
    echo "Downloaded file is corrupt!"
    echo "File hash ($url --> $downloadFile): sha512.$fileHash"
    echo "Control hash: sha512.$controlHash"
    echo "Abort."
    exit 1
  fi
}

function downloadAndExecute() {
  local url=${1:-}
  local fileName=${2:-}
  local controlHash=${3:-}
  local runAsRoot=${4:-}

  downloadAndVerify "$url" "$fileName" "$controlHash" true
  local tempFile=${UBUNTU_SETUP_LAST_DOWNLOADED_FILE:-}

  echo "Making file executable..."
  chmod +x "$tempFile"

  if [[ "$runAsRoot" == "true" ]]; then
    echo "Executing file '$tempFile' as root..."

    if [[ "$tempFile" == *".py" ]]; then
      sudo python3 "$tempFile"
    else
      sudo "$tempFile"
    fi
  else
    echo "Executing file '$tempFile'..."

    if [[ "$tempFile" == *".py" ]]; then
      python3 "$tempFile"
    else
      bash "$tempFile"
    fi
  fi
}

function appendUniqueTextToFile() {
  local line=${1:-}
  local filePath=${2:-}

  if ! command -v rg &>/dev/null; then
    sudo apt install -y ripgrep
  fi

  touch "$filePath"
  if ! rg -qUF "$line" "$filePath"; then
    printf '\n%s\n' "$line" >>"$filePath"
  fi
}

function appendUniqueLineToBashrc() {
  local line=${1:-}

  appendUniqueTextToFile "$line" "$HOME/.bashrc"
}

function getGsetting() {
  local schema=${1:-}
  local key=${2:-}
  local value=${3:-}

  if gsettings list-schemas | grep -Fxq "$schema"; then
    if gsettings list-keys "$schema" | grep -Fxq "$key"; then
      gsettings get "$schema" "$key"
    else
      echo "[UBUNTU SETUP] Missing key for gsettings schema $schema: $key"
      exit 1
    fi
  else
    echo "[UBUNTU SETUP] Missing gsettings schema: $schema"
    exit 1
  fi
}

function applyGsetting() {
  local schema=${1:-}
  local key=${2:-}
  local value=${3:-}

  if gsettings set "$schema" "$key" "$value"; then
    echo "gsettings: set $schema $key=$value"
  elif gsettings list-schemas | grep -Fxq "$schema"; then
    if ! gsettings list-keys "$schema" | grep -Fxq "$key"; then
      echo "[UBUNTU SETUP] Missing key for gsettings schema $schema: $key"
      exit 1
    fi
  else
    echo "[UBUNTU SETUP] Missing gsettings schema: $schema"
    exit 1
  fi
}

function configureFirewall() {
  echo "[UBUNTU SETUP] Setting up UFW (Uncomplicated Firewall)..."
  # keep SSH reachable before enabling default-deny incoming
  sudo ufw allow OpenSSH
  # ensure firewall is active and enabled on system startup
  sudo ufw enable
  # block common HTTP(S) ports used by local webservers
  sudo ufw deny 8080
  sudo ufw deny 3000
  # block default port for Ollama
  sudo ufw deny 11434

  # list current UFW configuration
  sudo ufw status numbered
}

function configureGnomeSettings() {
  if ! command -v gsettings &>/dev/null; then
    echo "[UBUNTU SETUP] Unexpected error: gsettings is not present!"
    echo "[UBUNTU SETUP] Abort."
    exit 1
  fi

  echo "[UBUNTU SETUP] Adjust GNOME desktop settings..."
  applyGsetting org.gnome.desktop.privacy remember-recent-files false
  applyGsetting org.gnome.desktop.privacy report-technical-problems false
  applyGsetting org.gnome.desktop.privacy send-software-usage-stats false
  applyGsetting org.gnome.desktop.interface clock-format '24h'
  applyGsetting org.gnome.desktop.calendar week-start-day 'monday'

  echo "[UBUNTU SETUP] Adjust GNOME user settings for Nautilus..."
  applyGsetting org.gnome.nautilus.preferences default-sort-order 'type'
  applyGsetting org.gnome.nautilus.preferences show-create-link true

  echo "[UBUNTU SETUP] Adjust GNOME user settings for Gedit..."
  applyGsetting org.gnome.gedit.preferences.editor display-line-numbers true
  applyGsetting org.gnome.gedit.preferences.editor highlight-current-line true
  applyGsetting org.gnome.gedit.preferences.editor bracket-matching true
  applyGsetting org.gnome.gedit.preferences.editor auto-indent true
  applyGsetting org.gnome.gedit.preferences.editor insert-spaces true
  applyGsetting org.gnome.gedit.preferences.editor tabs-size 'uint32 2'

  echo "[UBUNTU SETUP] Adjust GNOME user settings to disable new annoying tiling feature..."
  applyGsetting org.gnome.mutter.keybindings toggle-tiled-left "['<Super>Left']"
  applyGsetting org.gnome.mutter.keybindings toggle-tiled-right "['<Super>Right']"

  #echo "[UBUNTU SETUP] Adjust GNOME user settings to disable default shortcuts that interfere with IntelliJ..."
  #setGsettingIfSchemaExists org.gnome.desktop.wm.keybindings toggle-shaded "['disabled']"

  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]] || [[ "${UBUNTU_SETUP_CONFIGURE_LENAS_GSETTINGS:-}" == "1" ]]; then
    echo "[UBUNTU SETUP] Adjust GNOME user settings to disable default shortcuts that interfere with Tomb Raider games..."
    applyGsetting org.gnome.desktop.wm.keybindings move-to-workspace-down "['<Control><Shift>Down']"
    applyGsetting org.gnome.desktop.wm.keybindings move-to-workspace-left "['<Control><Shift>Left']"
    applyGsetting org.gnome.desktop.wm.keybindings move-to-workspace-right "['<Control><Shift>Right']"
    applyGsetting org.gnome.desktop.wm.keybindings move-to-workspace-up "['<Control><Shift>Up']"

    applyGsetting org.gnome.desktop.wm.keybindings switch-to-workspace-down "['<Alt><Shift>Down']"
    applyGsetting org.gnome.desktop.wm.keybindings switch-to-workspace-left "['<Alt><Shift>Left']"
    applyGsetting org.gnome.desktop.wm.keybindings switch-to-workspace-right "['<Alt><Shift>Right']"
    applyGsetting org.gnome.desktop.wm.keybindings switch-to-workspace-up "['<Alt><Shift>Up']"

    #echo "[UBUNTU SETUP] Set mouse acceleration profile to 'flat' to avoid drag and drop issues..."
    #setGsettingIfSchemaExists set org.gnome.desktop.peripherals.mouse accel-profile 'flat'
    #setGsettingIfSchemaExists set org.gnome.desktop.peripherals.mouse speed 'double 1.0'
  fi
}

function reconfigureGit() {
  if ! [ -f /usr/share/doc/git/contrib/credential/libsecret/git-credential-libsecret ]; then
    sudo apt install -y make gcc libsecret-1-0 libsecret-1-dev libglib2.0-dev
    sudo make -C /usr/share/doc/git/contrib/credential/libsecret

    if ! [ -f /usr/share/doc/git/contrib/credential/libsecret/git-credential-libsecret ]; then
      echo "Unexpected error: failed to build git-credential-libsecret!"
      echo "Abort."
      exit 1
    fi
  fi

  if [ -f ~/.gitconfig ]; then
    echo "Local git config file ~/.gitconfig already exists. Save existing config as backup in ~/.gitconfig.bak."

    if [ -f ~/.gitconfig.bak ]; then
      echo "Old backup file ~/.gitconfig.bak already exists. Moving ~/.gitconfig.bak to trash..."
      gio trash -f ~/.gitconfig.bak
    fi
    mv ~/.gitconfig ~/.gitconfig.bak
  fi

  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]] || [[ "${UBUNTU_SETUP_RECONFIGURE_LENAS_GIT:-}" == "1" ]]; then
    local publicKey="$HOME/.ssh/id_ed25519.pub"

    if ! [ -f "$publicKey" ]; then
      echo "Error: public key file is missing ($publicKey)"
      echo "Abort."
      exit 1
    fi

    echo "Creating .gitconfig for Lena <3..."
    git config --global user.name "Lena M."
    git config --global user.email "lena.miyamoto21@gmail.com"
    git config --global user.signingkey "$publicKey"
    git config --global commit.gpgsign true
    git config --global gpg.format ssh
  else
    echo "Creating .gitconfig for user ${UBUNTU_SETUP_USERNAME:-}..."
    git config --global user.name "${UBUNTU_SETUP_USERNAME:-}"
    git config --global user.email "${UBUNTU_SETUP_USERNAME:-}@mail.com"
  fi

  git config --global core.editor "code --wait"
  git config --global core.autocrlf input
  git config --global credential.helper /usr/share/doc/git/contrib/credential/libsecret/git-credential-libsecret
  git config --global pull.rebase true

  git config --global core.pager delta
  git config --global interactive.diffFilter "delta --color-only"
  git config --global delta.navigate true # jump through files with 'n' and 'N'
  git config --global delta.light false   # set to 'true' in case you use a light terminal theme
  git config --global merge.conflictstyle zdiff3

  git config --global alias.dft "diff --tool=difftastic"
  # shellcheck disable=SC2016
  git config --global difftool.difftastic.cmd 'difft "$LOCAL" "$REMOTE"'
  git config --global pager.difftool true

  echo "
### Copied from: https://blog.gitbutler.com/how-git-core-devs-configure-git ###

# clearly makes git better
[column]
	ui = auto
[branch]
	sort = -committerdate
[tag]
	sort = version:refname
[init]
	defaultBranch = main
[diff]
	algorithm = histogram
	colorMoved = plain
	mnemonicPrefix = true
	renames = true
[push]
	default = simple
	autoSetupRemote = true
	followTags = true
[fetch]
	prune = true
	pruneTags = true
	all = true

# why the hell not?
[help]
	autocorrect = prompt
[commit]
	verbose = true
[rerere]
	enabled = true
	autoupdate = true
[core]
	excludesfile = ~/.gitignore
[rebase]
	autoSquash = true
	autoStash = true
	updateRefs = true

# a matter of taste (uncomment if you dare)
[core]
	# fsmonitor = true
	# untrackedCache = true
" >>~/.gitconfig
}

function reconfigureVsCode() {
  local nodePath

  if [ -d ~/.vscode ]; then
    echo "Moving ~/.vscode to trash ..."
    gio trash -f ~/.vscode
  fi
  if [ -d ~/.config/Code ]; then
    echo "Moving ~/.config/Code to trash ..."
    gio trash -f ~/.config/Code
  fi

  mkdir -p ~/.config/Code/User

  if ! command -v shfmt &>/dev/null; then
    sudo apt install -y shfmt
  fi
  if ! command -v jq &>/dev/null; then
    sudo apt install -y jq
  fi
  if ! command -v fnm &>/dev/null || ! command -v node &>/dev/null; then
    installNodeJs
  fi

  fnm use 26
  nodePath="$FNM_DIR/node-versions/$(fnm current)/installation/bin/node"
  fnm use default

  if ! [ -x "$nodePath" ]; then
    echo "Unexpected error: could not detect Node.js 26 executable!"
    echo "Abort."
    exit 1
  fi

  echo "Installing commonly used VSCode extensions..."
  code --install-extension eamodio.gitlens
  code --install-extension redhat.vscode-yaml
  code --install-extension editorconfig.editorconfig
  code --install-extension sanaajani.taskrunnercode
  code --install-extension yzhang.markdown-all-in-one
  code --install-extension ms-vsliveshare.vsliveshare
  code --install-extension vscode-icons-team.vscode-icons

  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]] || [[ "${UBUNTU_SETUP_RECONFIGURE_LENAS_VSCODE:-}" == "1" ]]; then
    echo "Installing Lena's VSCode extensions <3..."
    code --install-extension mkhl.shfmt
    code --install-extension vitest.explorer
    code --install-extension dohe.godot-format
    code --install-extension geequlim.godot-tools
    code --install-extension timonwong.shellcheck
    code --install-extension dbaeumer.vscode-eslint
    code --install-extension esbenp.prettier-vscode
    code --install-extension rust-lang.rust-analyzer
    code --install-extension ms-playwright.playwright
    code --install-extension mads-hartmann.bash-ide-vscode

    echo "Installing VSCode themes for Lena <3..."
    code --install-extension atomiks.moonlight

    echo "Configuring user settings for Lena's VSCode <3..."
    echo '{}' |
      jq '."editor.tabSize" = 2' |
      jq '."editor.formatOnSave" = false' |
      jq '."editor.defaultFormatter" = "EditorConfig.EditorConfig"' |
      jq '."editor.autoIndentOnPaste" = true' |
      jq '."editor.snippetSuggestions" = "none"' |
      jq '."editor.inlineSuggest.enabled" = false' |
      jq '."editor.bracketPairColorization.independentColorPoolPerBracketType" = true' |
      jq '."editor.fontFamily" = "'\''SeriousShanns Nerd Font Mono'\'', '\''Droid Sans Mono'\'', monospace"' |
      jq '."github.copilot.nextEditSuggestions.enabled" = false' |
      jq '."terminal.integrated.defaultProfile.linux" = "fish"' |
      jq '."terminal.integrated.gpuAcceleration" = "off"' |
      jq '."js/ts.tsserver.node.path" = "'"$nodePath"'"' |
      jq '."js/ts.tsserver.maxMemory" = 10240' |
      jq '."vsicons.dontShowNewVersionMessage" = true' |
      jq '."window.zoomLevel" = 1.4' |
      jq '."workbench.colorTheme" = "Moonlight II"' |
      jq '."workbench.iconTheme" = "vscode-icons"' |
      jq '."workbench.localHistory.maxFileEntries" = 25' |
      jq '."workbench.localHistory.maxFileSize" = 512' \
        >~/.config/Code/User/settings.json

    installCustomFonts
  else
    echo "Configuring basic user settings for VSCode..."
    echo '{}' |
      jq '."editor.tabSize" = 2' |
      jq '."editor.formatOnSave" = false' |
      jq '."editor.defaultFormatter" = "EditorConfig.EditorConfig"' |
      jq '."editor.autoIndentOnPaste" = true' |
      jq '."editor.snippetSuggestions" = "none"' |
      jq '."editor.inlineSuggest.enabled" = false' |
      jq '."editor.bracketPairColorization.independentColorPoolPerBracketType" = true' |
      jq '."github.copilot.nextEditSuggestions.enabled" = false' |
      jq '."terminal.integrated.defaultProfile.linux" = "fish"' |
      jq '."terminal.integrated.gpuAcceleration" = "off"' |
      jq '."typescript.tsserver.nodePath" = "'"$nodePath"'"' |
      jq '."vsicons.dontShowNewVersionMessage" = true' |
      jq '."window.zoomLevel" = 1' |
      jq '."workbench.iconTheme" = "vscode-icons"' \
        >~/.config/Code/User/settings.json
  fi
}

function installEssentials() {
  echo "[UBUNTU SETUP] Install essential command line utilities..."
  sudo apt install -y apt-transport-https ca-certificates apparmor-profiles bubblewrap curl gpg jq

  if ! [ -f /etc/apparmor.d/bwrap-userns-restrict ]; then
    sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict
    sudo systemctl reload apparmor
  fi
}

function installCommandlineBasics() {
  echo "[UBUNTU SETUP] Install basic command line utilities..."
  sudo apt install -y libsecret-tools mesa-utils \
    fish net-tools plocate rhash pwgen \
    unzip zstd tar bzip2 xz-utils brotli rar unrar p7zip-full \
    ffmpeg imagemagick optipng pdftk-java libimage-exiftool-perl \
    texlive-latex-base texlive-latex-recommended texlive-fonts-recommended texlive-latex-extra texlive-extra-utils texlive-xetex
}

function installSystemUtils() {
  echo "[UBUNTU SETUP] Install basic system utilities..."
  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    sudo apt install -y keepassxc-minimal
  fi
  sudo apt install -y file-roller gparted usb-creator-gtk

  # open all archive files with file-roller instead of nautilus
  for mime in \
    application/zip \
    application/x-7z-compressed \
    application/x-rar \
    application/x-tar \
    application/gzip \
    application/x-bzip2 \
    application/x-xz \
    application/zstd \
    application/vnd.rar; do
    echo xdg-mime default org.gnome.FileRoller.desktop "$mime"
  done
}

function installMultimediaUtils() {
  echo "[UBUNTU SETUP] Installing various multi-media codecs and tools..."
  sudo apt install -y ubuntu-restricted-extras
}

function installMsFonts() {
  if ! read -r -n1 -d "" < <(fc-list | grep -oi "Arial.ttf\|Verdana.ttf\|times.ttf"); then
    echo "[UBUNTU SETUP] Installing MS core fonts..."
    # TODO does not work on Ubuntu 26.04!
    # automatically accepts the Microsoft End User License Agreement (EULA),
    # preventing the interactive prompt from the ttf-mscorefonts-installer
    echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections
    sudo apt install -y ttf-mscorefonts-installer fonts-crosextra-carlito fonts-crosextra-caladea
    sudo fc-cache -fv
  else
    echo "[UBUNTU SETUP] MS Core Fonts are already installed. Nothing to do."
  fi

  if ! read -r -n1 -d "" < <(fc-list | grep -oi "calibri.ttf"); then
    echo "[UBUNTU SETUP] Installing MS proprietary fonts..."
    sudo apt install -y cabextract fontforge
    downloadAndExecute https://gist.github.com/maxwelleite/10774746/raw/ttf-vista-fonts-installer.sh ttf-vista-fonts-installer.sh 5f7156c1f7598eaf65710061bd96d54a5e10843a78c4bd9cbdd18ed850c91401d464fa9ac7b2f1d245f51da1990e049d7b72bbf19a058fcd8951fb98ade830ce true
    # script calls `sudo fc-cache -fv` automatically after installation
  else
    echo "[UBUNTU SETUP] MS proprietary fonts are already installed. Nothing to do."
  fi
}

function installCustomFont() {
  local fontName=${1:-}
  local fontType=${2:-}
  local fontDirectoryName=${3:-}
  local url=${4:-}
  local fileName=${5:-}
  local controlHash=${6:-}

  local fontDirectory="/usr/share/fonts/$fontType/$fontDirectoryName"

  if ! [ -d "$fontDirectory" ]; then
    local fontSuffix

    if [[ "$fontType" == "opentype" ]]; then
      fontSuffix="*.otf"
    elif [[ "$fontType" == "truetype" ]]; then
      fontSuffix="*.ttf"
    else
      echo "Invalid font type: $fontType"
      exit 1
    fi

    echo "[UBUNTU SETUP] Downloading and installing $fontType font '$fontName'..."
    downloadAndVerify "$url" "$fileName" "$controlHash"
    sudo mkdir "$fontDirectory"
    sudo unzip -d "$fontDirectory" -j "${UBUNTU_SETUP_LAST_DOWNLOADED_FILE:-}" "$fontSuffix"

    UBUNTU_SETUP_CUSTOM_FONT_INSTALLED=1
  else
    echo "[UBUNTU SETUP] Font '$fontName' is already installed. Skip."
  fi
}

function installCustomFonts() {
  echo "[UBUNTU SETUP] Installing custom fonts..."

  installCustomFont \
    'Serious Shanns' \
    'opentype' \
    'serious-shanns' \
    'https://github.com/kaBeech/serious-shanns/releases/download/v6.0.0/SeriousShanns.zip' \
    'SeriousShanns.zip' \
    'e45bf5d84894b413bbbbdbcb96359321af6e081dc0cbb27272cbaa85114fb191f24f5bd8d12eb6f1c379d9384e9cd83d3b6c93a937bf4774e46543db2798c687'
  installCustomFont \
    'Montserrat' \
    'opentype' \
    'montserrat' \
    'https://www.1001fonts.com/download/montserrat.zip' \
    'montserrat.zip' \
    'ae0a63dbf2fe11f1321c1c906307cfa7ea3e3248dc510b5cb6edcaf43899b26b0e0488a87c24fc9e9b64d8bce89740560df751cc7ee6273070b2199ab8248a35'
  installCustomFont \
    'Peppy Pegasus' \
    'opentype' \
    'peppy-pegasus' \
    'https://font.download/dl/font/peppy-pegasus.zip' \
    'peppy-pegasus.zip' \
    'c4f547665c1a60956ad07c343d6b923c4ed3287b93b08de083d75ce21d3c2fa2c1e7fb49268f1f2ece2e3d5811622d115ef31cb1777ffb3aad2194587093e9f8'
  installCustomFont \
    'Magic Unicorn' \
    'truetype' \
    'magic-unicorn' \
    'https://dl.dafont.com/dl/?f=magic_unicorn' \
    'magic_unicorn.zip' \
    '75b5e780f07c1df881eb13b0bb58654e1ddbeb5978d9e954eeab6a7da0028ec43e84a73366f8241d71bb93330a7bfdfd2dd09a8619a4f75d0c7757fdb043bfc7'
  installCustomFont \
    'Magic Stary' \
    'opentype' \
    'magic-stary' \
    'https://dl.dafont.com/dl/?f=magic_stary' \
    'magic_stary.zip' \
    '456e4c750ba8736dcd53597eed965ac9c24c5d8db34503fb698fca1a90594da993ace44a0fb8ac7a79c5f562faf1394370e8242db452b44810c767f6c6aa9433'
  installCustomFont \
    'Bad Grunge' \
    'truetype' \
    'bad-grunge' \
    'https://dl.dafont.com/dl/?f=bad_grunge' \
    'bad-grunge.zip' \
    'f0add53663bc710e69184cb4439e9690526abe8ff762abd760456a9171585157148883e7cec198e912f1e00281b5fd4e772ea12fda065dc1517075b73e3648ac'
  installCustomFont \
    'Gunplay' \
    'opentype' \
    'gunplay' \
    'https://dl.dafont.com/dl/?f=gunplay' \
    'gunplay.zip' \
    '572c6241fa14f9714cfa3ede481fd3afd1a8a00fb9eb87031fbd3e5eb1884a7fd352b72fa799be73ef24ec8c11f73eccef0983122298310cc10852a54daa7529'

  if [[ "${UBUNTU_SETUP_CUSTOM_FONT_INSTALLED:-}" == "1" ]]; then
    sudo fc-cache -fv
  fi
}

function installFirefoxEsr() {
  if ! command -v firefox-esr &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Firefox ESR..."
    # from this guide: https://linuxconfig.org/how-to-install-firefox-without-snap-on-ubuntu-26-04
    sudo snap remove --purge firefox
    sudo add-apt-repository -y ppa:mozillateam/ppa
    sudo apt install -y fonts-lyx firefox-esr
  else
    echo "[UBUNTU SETUP] Firefox ESR is already installed. Nothing to do."
  fi
}

function installThunderbird() {
  if ! command -v thunderbird &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Thunderbird..."
    sudo snap install thunderbird
  else
    echo "[UBUNTU SETUP] Thunderbird is already installed. Nothing to do."
  fi
}

function installDiscord() {
  if ! command -v discord &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Discord..."
    sudo snap install discord
  else
    echo "[UBUNTU SETUP] Discord is already installed. Nothing to do."
  fi
}

function installSpotify() {
  if ! command -v spotify &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Spotify..."
    sudo snap install spotify
  else
    echo "[UBUNTU SETUP] Spotify is already installed. Nothing to do."
  fi
}

function installVsCode() {
  if ! command -v code &>/dev/null; then
    echo "[UBUNTU SETUP] Installing VSCode..."
    # TODO move into separate helper function
    if ! [ -f /usr/share/keyrings/microsoft.gpg ]; then
      curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
    fi
    echo "Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: amd64,arm64,armhf
Signed-By: /usr/share/keyrings/microsoft.gpg
" | sudo tee /etc/apt/sources.list.d/vscode.sources
    # update the package cache and install VS Code
    sudo apt update
    sudo apt install -y code

    reconfigureVsCode
  else
    echo "[UBUNTU SETUP] VSCode is already installed. Nothing to do."
  fi
}

function installFlatpak() {
  local disableSkipMessage=${1:-}

  if ! command -v flatpak &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Flatpak..."
    sudo apt install -y flatpak gnome-software-plugin-flatpak

    sudo flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

    flatpak update -y --noninteractive
    flatpak update -y --noninteractive --appstream

    installFlatseal
  elif [[ "$disableSkipMessage" != "true" ]]; then
    echo "[UBUNTU SETUP] Flatpak is already installed. Nothing to do."
  fi
}

function installFlathubPackage() {
  flatpakPackage=${1:-}
  appName=${2:-}

  installFlatpak true

  if ! flatpak info "$flatpakPackage" &>/dev/null; then
    echo "[UBUNTU SETUP] Installing $appName..."
    flatpak install -y --user flathub "$flatpakPackage"
    flatpak run --user "$flatpakPackage" &
    disown
  else
    echo "[UBUNTU SETUP] $appName is already installed via Flatpak. Nothing to do."
  fi
}

function installFlatseal() {
  installFlathubPackage com.github.tchx84.Flatseal Flatseal
}

function installVlc() {
  if ! command -v vlc &>/dev/null; then
    installFlathubPackage org.videolan.VLC "VLC Player"
  else
    echo "[UBUNTU SETUP] VLC Player is already installed. Nothing to do."
  fi
}

function installCine() {
  if ! command -v cine &>/dev/null; then
    installFlathubPackage io.github.diegopvlk.Cine Cine
  else
    echo "[UBUNTU SETUP] Cine is already installed. Nothing to do."
  fi
}

function installElement() {
  if ! command -v element-desktop &>/dev/null; then
    # The Flatpak version requires specific permissions for file access. By default, it may not access your files.
    # To allow access to common directories like Pictures, Videos, and Documents, use:
    # flatpak override --filesystem=xdg-pictures --filesystem=xdg-videos --filesystem=xdg-documents im.riot.Riot

    # In case you get "Electron has detected that encryption is not available on your keyring gnome_libsecret"
    # when opening the application, launch Flatseal and ensure dbus-session is enabled!
    installFlathubPackage im.riot.Riot Element
  else
    echo "[UBUNTU SETUP] Element is already installed. Nothing to do."
  fi
}

function installInkscape() {
  if ! command -v inkscape &>/dev/null; then
    installFlathubPackage org.inkscape.Inkscape Inkscape
  else
    echo "[UBUNTU SETUP] Inkscape is already installed. Nothing to do."
  fi
}

function installGimp() {
  if ! command -v gimp &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Gimp..."
    installFlatpak true

    if ! flatpak info org.gimp.GIMP &>/dev/null; then
      flatpak install -y --user https://flathub.org/repo/appstream/org.gimp.GIMP.flatpakref
      flatpak run --user org.gimp.GIMP &
      disown
    else
      echo "[UBUNTU SETUP] Gimp is already installed via Flatpak. Nothing to do."
    fi
  else
    echo "[UBUNTU SETUP] Gimp is already installed. Nothing to do."
  fi
}

function installBlender() {
  if ! command -v blender &>/dev/null; then
    installFlathubPackage org.blender.Blender Blender
  else
    echo "[UBUNTU SETUP] Blender is already installed. Nothing to do."
  fi
}

function installHeroic() {
  installFlathubPackage com.heroicgameslauncher.hgl "Heroic Games Launcher"
}

function installProtonUp() {
  installFlathubPackage net.davidotek.pupgui2 "ProtonUp-Qt"
}

function installMupen64Plus() {
  installFlathubPackage net.sourceforge.m64py.M64Py "Mupen64Plus + M64Py"
}

function installAzahar() {
  installFlathubPackage org.azahar_emu.Azahar Azahar
}

function installTorBrowser() {
  if ! command -v torbrowser-launcher &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Tor Browser..."
    sudo apt install -y torbrowser-launcher
  else
    echo "[UBUNTU SETUP] Tor Browser is already installed. Nothing to do."
  fi
}

function installBrave() {
  if ! command -v brave &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Brave..."
    sudo curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
    sudo curl -fsSLo /etc/apt/sources.list.d/brave-browser-release.sources https://brave-browser-apt-release.s3.brave.com/brave-browser.sources
    sudo apt update
    sudo apt install -y brave-browser
  else
    echo "[UBUNTU SETUP] Brave is already installed. Nothing to do."
  fi
}

function installEdge() {
  if ! command -v microsoft-edge &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Microsoft Edge..."
    # TODO move into separate helper function
    if ! [ -f /usr/share/keyrings/microsoft.gpg ]; then
      curl -sSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
    fi
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" | sudo tee /etc/apt/sources.list.d/microsoft-edge.list
    sudo apt update
    sudo apt install -y microsoft-edge-stable
  else
    echo "[UBUNTU SETUP] Microsoft Edge is already installed. Nothing to do."
  fi
}

function installSignal() {
  if ! command -v signal-desktop &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Signal..."

    # install official public software signing key
    curl -fsSL https://updates.signal.org/desktop/apt/keys.asc | gpg --dearmor >"signal-desktop-keyring.gpg"
    sudo install -m 0644 "signal-desktop-keyring.gpg" /usr/share/keyrings/signal-desktop-keyring.gpg

    # add repository to our list of repositories
    curl -fsSL https://updates.signal.org/static/desktop/apt/signal-desktop.sources -o "signal-desktop.sources"
    sudo install -m 0644 "signal-desktop.sources" /etc/apt/sources.list.d/signal-desktop.sources

    sudo apt update
    sudo apt install -y signal-desktop
  else
    echo "[UBUNTU SETUP] Signal is already installed. Nothing to do."
  fi
}

function installSteam() {
  if ! command -v steam &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Steam..."
    curl -fsSL https://repo.steampowered.com/steam/archive/stable/steam.gpg | sudo gpg --dearmor -o /usr/share/keyrings/steam.gpg
    echo "Types: deb
URIs: https://repo.steampowered.com/steam/
Suites: stable
Components: steam
Architectures: amd64 i386
Signed-By: /usr/share/keyrings/steam.gpg" | sudo tee /etc/apt/sources.list.d/steam.sources

    sudo dpkg --add-architecture i386
    sudo apt update
    sudo apt install -y steam-launcher
    # we can safely delete this again because the steam-launcher
    # installer creates a /etc/apt/sources.list.d/steam-stable.list file on its own
    sudo rm -vf /etc/apt/sources.list.d/steam.sources
    sudo apt update

    if ! [ -d ~/.local/share/Steam ]; then
      mkdir -p ~/.local/share/Steam
    fi
    if ! [ -f ~/.local/share/Steam/steam_dev.cfg ] || ! grep -qE '^@ShaderBackgroundProcessingThreads[[:space:]]+[[:digit:]]+' ~/.local/share/Steam/steam_dev.cfg; then
      echo "@ShaderBackgroundProcessingThreads $(nproc)" >>~/.local/share/Steam/steam_dev.cfg
    fi

    installProtonUp
  else
    echo "[UBUNTU SETUP] Steam is already installed. Nothing to do."
  fi
}

function installPython() {
  if ! command -v uv &>/dev/null; then
    echo "[UBUNTU SETUP] Installing uv..."
    installRust
    cargo install --locked uv

    echo "[UBUNTU SETUP] Installing Python 3.12 via uv..."
    uv python install --default 3.12
    uv tool install ruff
    uv tool install ty
  else
    echo "[UBUNTU SETUP] Python and uv are already installed. Nothing to do."
  fi
}

function installJava() {
  if ! command -v javac &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Java..."
    sudo apt install -y openjdk-17-jdk

    echo "Adding JAVA_HOME to ~/.bashrc..."
    export JAVA_HOME
    JAVA_HOME=$(readlink -f /usr/bin/javac | sed 's:/bin/javac::')
    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export JAVA_HOME=$(readlink -f /usr/bin/javac | sed "s:/bin/javac::")'
  else
    echo "[UBUNTU SETUP] Java is already installed. Nothing to do."
  fi
}

function installGradle() {
  if ! command -v gradle &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Gradle..."
    sudo apt install -y gradle

    echo "Adding GRADLE_HOME to ~/.bashrc..."
    export GRADLE_HOME
    GRADLE_HOME=$(readlink -f /usr/bin/gradle | sed 's:/bin/gradle::')
    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export GRADLE_HOME=$(readlink -f /usr/bin/gradle | sed "s:/bin/gradle::")'
  else
    echo "[UBUNTU SETUP] Gradle is already installed. Nothing to do."
  fi
}

function installAndroidSdk() {
  if ! command -v sdkmanager &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Android SDK..."
    installJava
    installGradle

    echo "[UBUNTU SETUP] Downloading and installing cmdline-tools (Android SDK)..."
    downloadAndVerify "https://dl.google.com/android/repository/commandlinetools-linux-14742923_latest.zip" "commandlinetools-linux-14742923_latest.zip" "b65e830d7655fb39cc9eee669806977f462c49375807ef2c6487fabcc9afdbc210465ce6a1e2429ff95c74ca519d1239daf9a403c30b8d0bdb7a0962af656c8e"
    mkdir -p ~/.local/android/sdk/.temp
    unzip "${UBUNTU_SETUP_LAST_DOWNLOADED_FILE:-}" -d ~/.local/android/sdk/.temp

    # TODO fix broken setup
    # mv: cannot overwrite '~/.local/android/sdk/cmdline-tools/latest/bin': Directory not empty
    # mv: cannot overwrite '~/.local/android/sdk/cmdline-tools/latest/lib': Directory not empty
    mkdir -p ~/.local/android/sdk/cmdline-tools/latest
    mv ~/.local/android/sdk/.temp/cmdline-tools/* ~/.local/android/sdk/cmdline-tools/latest
    rm -rf ~/.local/android/sdk/.temp

    sudo apt install -y libxcb-cursor0

    echo "Adding ANDROID_HOME to ~/.bashrc..."
    export ANDROID_HOME="$HOME/.local/android/sdk"
    export ANDROID_SDK_ROOT="$ANDROID_HOME"
    export ANDROID_AVD_HOME="$HOME/.local/android/avd"
    export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export ANDROID_HOME="$HOME/.local/android/sdk"'
    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export ANDROID_SDK_ROOT="$ANDROID_HOME"'
    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export ANDROID_AVD_HOME="$HOME/.local/android/avd"'
    # shellcheck disable=SC2016
    appendUniqueLineToBashrc 'export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"'

    echo 'y' | sdkmanager "emulator" "platform-tools" "build-tools;36.0.0" "platforms;android-36" "system-images;android-36;google_apis;x86_64"
    echo 'no' | avdmanager create avd --force --name Pixel10_API36 --package "system-images;android-36;google_apis;x86_64"
    # start android emulator with: `emulator -avd Pixel10_API36 -netdelay none -netspeed full`
  else
    echo "[UBUNTU SETUP] Android SDK is already installed. Nothing to do."
  fi
}

function installPodman() {
  if ! command -v podman &>/dev/null || ! command -v podman-compose &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Podman..."
    sudo apt install -y podman podman-compose
  else
    echo "[UBUNTU SETUP] Podman is already installed. Nothing to do."
  fi
}

function requirePodmanVersion5() {
  local podmanMajorVersion

  installPodman

  podmanMajorVersion=$(podman --version | grep -oE '[0-9]+' | head -n1)

  if [[ "$podmanMajorVersion" != "5" ]]; then
    echo "[UBUNTU SETUP] Unsupported Podman major version: ${podmanMajorVersion:-unknown}"
    echo "[UBUNTU SETUP] Podman 5 is required. Abort."
    exit 1
  fi
}

function recreateManagedContainer() {
  local containerName=${1:-}
  local image=${2:-}
  local serviceLabel=${3:-}
  local existingImage

  if podman container exists "$containerName"; then
    existingImage=$(podman inspect --format '{{.ImageName}}' "$containerName" 2>/dev/null || true)

    if [[ "$existingImage" != "$image" ]]; then
      echo "[UBUNTU SETUP] A container named '$containerName' already exists, but it does not use image '$image'."
      echo "[UBUNTU SETUP] Refusing to replace an unrelated container. Abort."
      exit 1
    fi

    echo "[UBUNTU SETUP] Existing $serviceLabel container detected. Recreating it with the current configuration..."
    podman rm -f "$containerName"
  fi
}

function installOpenWebUi() {
  local image="ghcr.io/open-webui/open-webui:main"
  local containerName="open-webui"
  local openWebUiRootDir="$HOME/.open-webui"
  local openWebUiDataDir="$openWebUiRootDir/data"
  local secretKeyFile="$openWebUiRootDir/webui-secret-key"
  local webUiPort="3000"
  local llamaCppBaseUrl="http://host.containers.internal:8080/v1"
  local webUiSecretKey

  echo "[UBUNTU SETUP] Installing Open WebUI..."

  requirePodmanVersion5

  if ! command -v openssl &>/dev/null; then
    sudo apt install -y openssl
  fi

  mkdir -p "$openWebUiDataDir"

  if ! [ -f "$secretKeyFile" ]; then
    echo "[UBUNTU SETUP] Generating persistent Open WebUI secret key..."
    umask 077
    openssl rand -hex 32 >"$secretKeyFile"
  fi

  webUiSecretKey=$(<"$secretKeyFile")

  if [[ -z "$webUiSecretKey" ]]; then
    echo "Error: Open WebUI secret key file is empty ($secretKeyFile)"
    echo "Abort."
    exit 1
  fi

  recreateManagedContainer "$containerName" "$image" "Open WebUI"

  echo "[UBUNTU SETUP] Pulling documented Open WebUI image '$image'..."
  podman pull "$image"

  echo "[UBUNTU SETUP] Starting Open WebUI container on http://127.0.0.1:$webUiPort ..."
  podman run -d \
    --name "$containerName" \
    --hostname "$containerName" \
    --pull newer \
    --publish 127.0.0.1:$webUiPort:8080 \
    --volume "$openWebUiDataDir:/app/backend/data:U" \
    --env "TZ=$(cat /etc/timezone)" \
    --env "WEBUI_URL=http://127.0.0.1:$webUiPort" \
    --env "WEBUI_SECRET_KEY=$webUiSecretKey" \
    --env "ENABLE_OPENAI_API=true" \
    --env "OPENAI_API_BASE_URL=$llamaCppBaseUrl" \
    --env "OPENAI_API_KEY=" \
    "$image"

  echo "[UBUNTU SETUP] Open WebUI container is running."
  echo "[UBUNTU SETUP] Open http://127.0.0.1:$webUiPort to finish the first-run setup."
  echo "[UBUNTU SETUP] OpenAI-compatible backend is preconfigured for llama.cpp at: $llamaCppBaseUrl"
  echo "[UBUNTU SETUP] Persistent data directory: $openWebUiDataDir"
  echo "[UBUNTU SETUP] Persistent secret key file: $secretKeyFile"
}

function installOpenSshServer() {
  local image="lscr.io/linuxserver/openssh-server:latest"
  local containerName="openssh-server"
  local opensshRootDir="$HOME/.openssh-server"
  local opensshConfigDir="$opensshRootDir/config"
  local publicKeyFile="$HOME/.ssh/id_ed25519.pub"
  local sshPort="2222"
  local publicKey

  echo "[UBUNTU SETUP] Installing OpenSSH Server..."

  if ! [ -f "$publicKeyFile" ]; then
    echo "Error: expected public key file is missing ($publicKeyFile)"
    echo "Abort."
    exit 1
  fi

  requirePodmanVersion5

  publicKey=$(<"$publicKeyFile")

  mkdir -p "$opensshConfigDir"

  recreateManagedContainer "$containerName" "$image" "OpenSSH Server"

  echo "[UBUNTU SETUP] Pulling documented OpenSSH Server image '$image'..."
  podman pull "$image"

  echo "[UBUNTU SETUP] Starting OpenSSH Server container on ssh://127.0.0.1:$sshPort ..."
  podman run -d \
    --name "$containerName" \
    --hostname "$containerName" \
    --pull newer \
    --publish 127.0.0.1:$sshPort:2222 \
    --volume "$opensshConfigDir:/config:U" \
    --env "PUID=$UBUNTU_SETUP_USER_ID" \
    --env "PGID=$UBUNTU_SETUP_GROUP_ID" \
    --env "TZ=$(cat /etc/timezone)" \
    --env "PUBLIC_KEY=$publicKey" \
    --env "PASSWORD_ACCESS=false" \
    --env "SUDO_ACCESS=false" \
    --env "USER_NAME=${UBUNTU_SETUP_USERNAME:-}" \
    --env "LOG_STDOUT=true" \
    "$image"

  echo "[UBUNTU SETUP] OpenSSH Server container is running."
  echo "[UBUNTU SETUP] Connect with: ssh -p $sshPort ${UBUNTU_SETUP_USERNAME:-}@127.0.0.1"
  echo "[UBUNTU SETUP] Persistent config directory: $opensshConfigDir"
  echo "[UBUNTU SETUP] Authorized keys were seeded from: $publicKeyFile"
}

function installGitea() {
  local image="docker.gitea.com/gitea:1-rootless"
  local containerName="gitea"
  local giteaRootDir="$HOME/.gitea"
  local giteaDataDir="$giteaRootDir/data"
  local giteaConfigDir="$giteaRootDir/config"

  echo "[UBUNTU SETUP] Installing Gitea..."

  requirePodmanVersion5

  mkdir -p "$giteaDataDir" "$giteaConfigDir"

  recreateManagedContainer "$containerName" "$image" "Gitea"

  echo "[UBUNTU SETUP] Pulling official Gitea rootless image '$image'..."
  podman pull "$image"

  echo "[UBUNTU SETUP] Starting Gitea rootless container on http://127.0.0.1:3001 ..."
  podman run -d \
    --name "$containerName" \
    --user "$UBUNTU_SETUP_USER_ID:$UBUNTU_SETUP_GROUP_ID" \
    --pull newer \
    --publish 127.0.0.1:3001:3000 \
    --publish 127.0.0.1:2222:2222 \
    --volume "$giteaDataDir:/var/lib/gitea:U" \
    --volume "$giteaConfigDir:/etc/gitea:U" \
    --volume /etc/timezone:/etc/timezone:ro \
    --volume /etc/localtime:/etc/localtime:ro \
    --env GITEA__database__DB_TYPE=sqlite3 \
    --env GITEA__server__ROOT_URL=http://127.0.0.1:3001/ \
    --env GITEA__server__SSH_DOMAIN=127.0.0.1 \
    --env GITEA__server__SSH_PORT=2222 \
    --env GITEA__server__START_SSH_SERVER=true \
    "$image"

  echo "[UBUNTU SETUP] Gitea container is running."
  echo "[UBUNTU SETUP] Open http://127.0.0.1:3001 to finish the first-run setup."
  echo "[UBUNTU SETUP] Persistent data directory: $giteaDataDir"
  echo "[UBUNTU SETUP] Persistent config directory: $giteaConfigDir"
  echo "[UBUNTU SETUP] SSH clone URL base will use port 2222 on localhost."
}

function installVeracrypt() {
  if ! command -v veracrypt &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Veracrypt..."
    sudo add-apt-repository ppa:unit193/encryption -y
    sudo apt update
    sudo apt install -y veracrypt
  else
    echo "[UBUNTU SETUP] Veracrypt is already installed. Nothing to do."
  fi
}

function installOllama() {
  if ! command -v ollama &>/dev/null; then
    local graphicsCardName
    local preferredModel="qwen2.5-coder:7b-instruct-q4_K_M"

    echo "[UBUNTU SETUP] Installing Ollama..."
    downloadAndExecute https://ollama.com/install.sh install-ollama.sh 087e24f4444544e4387b669df0bf945cffcbbcdfd7f69e8bc5a980a51b0d2f024e16678b0c1a8f2fcca581f0984153127e75be9d6aa8294a0c97055755e55880

    echo "Adding OLLAMA_AUTH_TOKEN to ~/.bashrc..."
    export OLLAMA_AUTH_TOKEN="ollama"
    appendUniqueLineToBashrc 'export OLLAMA_AUTH_TOKEN="ollama"'

    echo "Adding OLLAMA_MAX_LOADED_MODELS to ~/.bashrc..."
    export OLLAMA_MAX_LOADED_MODELS=1
    appendUniqueLineToBashrc 'export OLLAMA_MAX_LOADED_MODELS=1'

    echo "Adding OLLAMA_KEEP_ALIVE to ~/.bashrc..."
    export OLLAMA_KEEP_ALIVE="5m"
    appendUniqueLineToBashrc 'export OLLAMA_KEEP_ALIVE="5m"'

    graphicsCardName=$(lspci | grep -i 'vga\|3d\|display' | grep -ioE '\[([A-Za-z0-9 ]+)\]' | sed -E 's/^\[(.+)\]$/\1/')

    if lspci | grep -i 'vga\|3d\|display' | grep -q '[GeForce RTX 2070 SUPER]'; then
      echo "[UBUNTU SETUP] Installing Qwen3-Coder (14B with Q4_K_M quantization; 4-bit, optimized for efficiency and performance) model for agentic coding..."
      ollama pull "$preferredModel"
      ollama list
    else
      local encodedGraphicsCardName

      # shellcheck disable=SC2001
      encodedGraphicsCardName=$(echo "$graphicsCardName" | sed 's/ /+/g')

      echo "[UBUNTU SETUP] Could not auto-detect appropriate Ollama coding model for your graphics card: $graphicsCardName"
      echo "[UBUNTU SETUP] Check out this link to find a suitable model for your hardware setup: https://search.brave.com/ask?q=Best+Ollama+coding+model+for+$encodedGraphicsCardName+in+$(date +%Y)"
    fi
  else
    echo "[UBUNTU SETUP] Ollama is already installed."
  fi
}

function installLlamaCpp() {
  if ! command -v llama-cli &>/dev/null; then
    local llamaCppProjectDir="$HOME/Downloads/git/ggml-org/llama.cpp"

    echo "[UBUNTU SETUP] Installing llama.cpp..."
    sudo apt install -y git build-essential llvm clang g++-14 ccache cmake libssl-dev libopenblas-dev libcurl4-openssl-dev zlib1g-dev nvidia-cuda-toolkit

    if [ -d "$llamaCppProjectDir" ]; then
      cd "$llamaCppProjectDir"
      git fetch
    else
      mkdir -p "$llamaCppProjectDir"
      git clone https://github.com/ggml-org/llama.cpp.git "$llamaCppProjectDir"
      cd "$llamaCppProjectDir"
    fi

    # check out latest release tag
    git checkout "$(git describe --tags --abbrev=0 --match 'b*')"

    cmake -B build -DBUILD_SHARED_LIBS=OFF -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS -DGGML_CUDA=ON
    cmake --build build --config Release -j "$(nproc --all)"
    sudo cmake --install build

    if [ -f ~/.config/opencode/opencode.json ]; then
      mv -f ~/.config/opencode/opencode.json ~/.config/opencode/opencode.json.bak
      jq '.provider += {
  "llama.cpp": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "llama-server (local)",
    "options": {
      "baseURL": "http://localhost:8080/v1"
    },
    "models": {
      "qwen3.5-9b-local": {
        "name": "Qwen3.5 9B Q4_K_M (local)",
        "limit": {
          "context": 32768,
          "output": 32768
        }
      }
    }
  }
}' ~/.config/opencode/opencode.json.bak >~/.config/opencode/opencode.json
    fi

    if [ -f ~/.claude/settings.json ]; then
      mv -f ~/.claude/settings.json ~/.claude/settings.json.bak
      jq '.env += {
    "ANTHROPIC_AUTH_TOKEN": "llama.cpp",
    "ANTHROPIC_BASE_URL": "http://localhost:8080",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0"
  }' ~/.claude/settings.json.bak >~/.claude/settings.json
    fi

    llama-cli --version
  else
    echo "[UBUNTU SETUP] llama.cpp is already installed."
  fi

  echo Start llama-server on localhost:8080 with:
  echo llama-server --hf-repo 'Jackrong/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-v2-GGUF' --hf-file 'Qwen3.5-9B.Q4_K_M.gguf' --port 8080 \
    -c 61440 \
    -ngl 99 \
    -fa on \
    --no-mmproj \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --jinja \
    --temp 0.4 \
    --top-p 0.95 \
    --top-k 20 \
    --presence-penalty 1.5 \
    --repeat-penalty 1.0
}

function installOpenCode() {
  if ! command -v opencode &>/dev/null; then
    echo "[UBUNTU SETUP] Installing OpenCode..."
    downloadAndExecute https://opencode.ai/install install-opencode.sh 5627a0f3ddb896405929cb7718d00df8c0be33a228318106c091b4d553ef48623c1a7d9fe3ccdedb9509f6e4f89e1daf5451c181f6fe51b976ac5c2a6bcb7fe3

    if ! [ -d ~/.config/opencode ]; then
      mkdir ~/.config/opencode
      # shellcheck disable=SC2016
      echo '{
  "$schema": "https://opencode.ai/config.json",
  "provider": {}
}' | tee ~/.config/opencode/opencode.json
    fi
  else
    echo "[UBUNTU SETUP] OpenCode is already installed."
  fi
}

function installClaudeCode() {
  if ! command -v claude &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Claude Code..."
    downloadAndExecute https://claude.ai/install.sh install-claude.sh dbb675d60d4cd30257e5f89e8c9f10f73d920ba07c11699ebc57d1210424ae17a140ca600dd34cacf386ea08c4801817a0bb7afc7ec2a646035ff5ccc48f482d

    if ! [ -d ~/.claude ]; then
      mkdir ~/.claude
      if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
        cp "$SCRIPT_DIR/agent-templates/claude-global/settings.json" ~/.claude/settings.json
        sed -i "s|<USER-HOME-DIR>|$HOME|g" ~/.claude/settings.json
        cp "$SCRIPT_DIR/agent-templates/claude-global/permissions.json" ~/.claude/permissions.json
        cp "$SCRIPT_DIR/agent-templates/claude-global/CLAUDE.md" ~/.claude/CLAUDE.md
        echo "[UBUNTU SETUP] Set ANTHROPIC_AUTH_TOKEN in ~/.claude/settings.json (template leaves a placeholder)."
      else
        echo '{
  "env": {}
}' | tee ~/.claude/settings.json
      fi
    fi

    if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
      claude plugin marketplace add lena-miyamoto/UtilityScripts
      claude plugin marketplace update lena-miyamoto

      claude plugin install tool-permissions@lena-miyamoto
      claude plugin update tool-permissions@lena-miyamoto

      claude plugin install statusline@lena-miyamoto
      claude plugin update statusline@lena-miyamoto
    fi
  else
    echo "[UBUNTU SETUP] Claude Code is already installed."
  fi
}

function installNodeJs() {
  if ! command -v fnm &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Fast Node Manager (fnm)..."
    installRust
    cargo install --locked fnm

    # shellcheck disable=SC2016
    appendUniqueTextToFile 'eval "$(fnm env --use-on-cd --shell bash)"' ~/.bashrc

    if command -v fish && [ -d ~/.config/fish/conf.d/ ]; then
      echo "Adding FNM env vars to Fish shell config..."
      cat >~/.config/fish/conf.d/fnm.fish <<<"fnm env --use-on-cd --shell fish | source"
    fi
    if command -v zsh &>/dev/null; then
      echo "Adding FNM env vars to ~/.zshrc..."
      # shellcheck disable=SC2016
      appendUniqueTextToFile 'eval "$(fnm env --use-on-cd --shell zsh)"' ~/.zshrc
    fi
  else
    echo "[UBUNTU SETUP] Fast Node Manager (fnm) is already installed."
  fi

  if ! command -v node &>/dev/null || [[ "$(node -v)" != "v26."* ]]; then
    echo "[UBUNTU SETUP] Installing and activating Node.js 24 and 26 via fnm..."

    export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

    fnm install 24 --corepack-enabled
    fnm use 24
    npm install -g --allow-scripts=esbuild npm@latest pnpm@latest typescript@latest tsx@latest rimraf@latest corepack@latest

    fnm install 26
    fnm use 26
    npm install -g --allow-scripts=esbuild npm@latest pnpm@latest typescript@latest tsx@latest rimraf@latest corepack@latest
    corepack enable

    fnm default 26
    fnm use default
  else
    echo "[UBUNTU SETUP] Node.js 26 is already installed via fnm, nothing to do."
  fi
}

function installGodot() {
  if ! command -v fgvm &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Friendly Godot Version Manager (fgvm)..."
    downloadAndVerify https://github.com/patricktcoakley/fgvm/releases/download/v2.0.2/fgvm-linux-x64.zip fgvm-linux-x64.zip 40f9c023c6d4398f0444ba15895aea6080faaf278a4c42ffc588f548a0310d3073279748354cf5cf059ad9cb9880f2716ceab34833a972791b9ceb34dd9e35d0
    unzip "$UBUNTU_SETUP_LAST_DOWNLOADED_FILE" -d ~/.local/bin
    chmod 755 ~/.local/bin/fgvm
  else
    echo "[UBUNTU SETUP] Friendly Godot Version Manager (fgvm) is already installed."
  fi

  if ! command -v godot &>/dev/null || [[ "$(godot --version 2>/dev/null)" != "4.5."* ]]; then
    echo "[UBUNTU SETUP] Installing and activating latest Godot version via fgvm..."
    fgvm install 4.5-stable
    fgvm set 4.5
    ln "$(fgvm which --json | jq -r '.symlinkPath')" ~/.local/bin/godot
  else
    echo "[UBUNTU SETUP] Godot is already installed, nothing to do."
  fi
}

function installRust() {
  if ! command -v rustup &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Rust..."
    downloadAndVerify https://sh.rustup.rs install-rustup.sh 494ddf67a104d5deb49380968ecccd8648ee0d7a3e61a8fa45b4dfd3bdc51ba8777922ed0e1864bf81ba78ce718bd40c55c1835c328df3cd1cd0d17312411460 true
    chmod +x "$UBUNTU_SETUP_LAST_DOWNLOADED_FILE"
    sh "$UBUNTU_SETUP_LAST_DOWNLOADED_FILE" -y

    # shellcheck disable=SC1090
    . ~/.cargo/env

    rustup update
    rustup default stable

    sudo apt install -y build-essential pkg-config libssl-dev

    cargo install cargo-update
  else
    echo "[UBUNTU SETUP] Rust is already installed. Nothing to do."
  fi
}

function installGit() {
  if ! command -v git &>/dev/null; then
    echo "[UBUNTU SETUP] Installing Git..."
    sudo apt install -y git git-lfs fzf
    git lfs install

    installRust
    sudo apt install -y ripgrep fd-find git-delta eza
    cargo install bat watchexec-cli difftastic

    # shellcheck disable=SC2016
    local gitUtilsAliases='# use eza as ls-replacement with icons and details
alias ls='"'"'eza --icons --group-directories-first'"'"'
alias ll='"'"'eza -lh --icons --group-directories-first'"'"'

# replace cat with bat (for syntax highlighting)
alias cat='"'"'bat -pp'"'"'

# switch branches interactively with fzf
alias gcb='"'"'git branch -a | fzf | xargs git switch'"'"'

'

    printf "%s" "$gitUtilsAliases" >>~/.bashrc
    # shellcheck disable=SC2016
    printf "%s" "$gitUtilsAliases" | sed 's/$(/(/g' >~/.config/fish/conf.d/git-utils-aliases.fish

    reconfigureGit
  else
    echo "[UBUNTU SETUP] Git is already installed. Nothing to do."
  fi
}

function installGitHubCli() {
  if ! command -v gh &>/dev/null; then
    echo "[DT UBUNTU SETUP] Installing GitHub CLI..."
    sudo apt install -y curl gpg ca-certificates

    sudo curl -fsSLo /usr/share/keyrings/githubcli-archive-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg
    echo "Types: deb
URIs: https://cli.github.com/packages
Suites: stable
Components: main
Architectures: $(dpkg --print-architecture)
Signed-By: /usr/share/keyrings/githubcli-archive-keyring.gpg" | sudo tee /etc/apt/sources.list.d/github-cli.sources

    sudo apt update
    sudo apt install -y gh
  else
    echo "[DT UBUNTU SETUP] GitHub CLI is already installed. Nothing to do."
  fi
}

function installDevTools() {
  echo "[UBUNTU SETUP] Installing essential dev-tools..."
  sudo apt install -y fish zsh shfmt build-essential llvm clang ccache cmake gdb lldb

  installGit
  installGitHubCli
  installPython
  installRust
  installNodeJs
  installVsCode

  # install cli tools frequently used by AI agents
  sudo apt install -y jq yq xq miller csvkit html2text \
    ripgrep fzf fd-find eza sd tokei hyperfine du-dust duf procs xh git-delta \
    ripgrep-all groff poppler-utils tesseract-ocr mupdf mupdf-tools
  uv tool install 'yt-dlp[default,curl-cffi]'
  cargo install bat watchexec-cli difftastic ast-grep

  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    installJava
    installGradle
    installClaudeCode

    #installAndroidSdk
    #installGodot
  fi
}

function installGnomeShell() {
  echo "[UBUNTU SETUP] Installing gnome-shell and related utilities..."
  sudo apt install -y ubuntu-gnome-desktop gnome-shell-extension-manager gnome-browser-connector gnome-tweaks dconf-editor alacarte gnome-terminal gedit gthumb
  gnome-extensions disable ubuntu-dock@ubuntu.com || true
  configureGnomeSettings
}

function startUbuntuSetup() {
  if [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]]; then
    echo "[UBUNTU SETUP] Starting basic setup for user ${UBUNTU_SETUP_USERNAME:-}..."
  elif [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    echo "[UBUNTU SETUP] Starting setup for Lena <3..."
  fi

  # set up UFW (Uncomplicated Firewall)
  configureFirewall

  echo "[UBUNTU SETUP] Updating packages..."
  sudo apt update
  sudo apt upgrade -y

  # set up the basics
  installFlatpak
  installGnomeShell
  installSystemUtils
  installMultimediaUtils
  installCommandlineBasics

  # disable useless snapshots for snap packages to safe time
  sudo snap set system snapshots.automatic.retention=no
  # install snap packages
  installDiscord
  installSpotify
  installFirefoxEsr
  installThunderbird

  # install flatpak packages
  installVlc
  installCine
  installGimp
  installInkscape
  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    installBlender
    installElement
  fi

  # install apt packages
  installTorBrowser
  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    installBrave
    installEdge
    installSignal
    installVeracrypt
    installPodman
  fi

  # install gaming setup
  installSteam
  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    installHeroic
    installAzahar
    installMupen64Plus
  fi

  # install fonts
  installMsFonts
  if [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    installCustomFonts
  fi

  # install dev tools
  installDevTools

  # auto-install recommended graphics drivers
  sudo ubuntu-drivers install

  # TODO ensure that all files have the correct architecture(s) set!
  # auto-converts old *.list to new *.sources format in /etc/apt
  #sudo apt modernize-sources

  sudo apt update
  sudo apt upgrade -y
  sudo apt autoremove -y --fix-broken

  sudo snap refresh

  if command -v flatpak &>/dev/null; then
    flatpak uninstall -y --unused
    flatpak update -y --noninteractive
  fi

  if command -v uv &>/dev/null; then
    uv tool upgrade --all
  fi

  if command -v cargo &>/dev/null; then
    cargo install-update --all
  fi

  sudo fwupdmgr refresh --force
  sudo fwupdmgr update

  echo "[UBUNTU SETUP] Setup complete!"
  exit 0
}

function printHelpText() {
  echo "Usage: ./ubuntu-setup.sh [OPTION]"
  echo "Installs and configures Ubuntu."
  echo
  echo "  -h, --help                      prints this help text"
  echo "  --basic-setup                   run only essential install and configure only the most relevant options"
  echo "  --lenas-setup                   run full install and configure all available options (except for openssh-server)"
  echo "  --install-local-ai              installs Node.js and Claude Code"
  echo "  --install-godot                 installs Godot 4.5 via Friendly Godot Version Manager (fgvm)"
  echo "  --install-openssh-server        installs openssh-server for local testing"
  echo "  --configure-gsettings           configures useful GNOME settings"
  echo "  --configure-lenas-gsettings     same as --configure-gsettings, but with private extra settings for Lena <3"
  echo "  --reconfigure-git               deletes local git config and reconfigures it from scratch"
  echo "  --reconfigure-lenas-git         same as --reconfigure-git, but with private extra settings for Lena <3"
  echo "  --reconfigure-vscode            deletes local VSCode config and reconfigures it from scratch"
  echo "  --reconfigure-lenas-vscode      same as --reconfigure-vscode, but with private extra settings for Lena <3"
}

## MAIN ##
if [ $# -eq 0 ]; then
  echo "Missing arguments."
  echo
  printHelpText
  exit 1
fi

for arg in "$@"; do
  if [[ "$arg" == "-h" ]] || [[ "$arg" == "--help" ]]; then
    printHelpText
    exit 0
  elif [[ "$arg" == "--basic-setup" ]]; then
    UBUNTU_SETUP_BASIC_SETUP=1
  elif [[ "$arg" == "--lenas-setup" ]]; then
    UBUNTU_SETUP_LENAS_SETUP=1
  elif [[ "$arg" == "--reconfigure-git" ]]; then
    UBUNTU_SETUP_RECONFIGURE_GIT=1
  elif [[ "$arg" == "--reconfigure-lenas-git" ]]; then
    UBUNTU_SETUP_RECONFIGURE_LENAS_GIT=1
  elif [[ "$arg" == "--reconfigure-vscode" ]]; then
    UBUNTU_SETUP_RECONFIGURE_VSCODE=1
  elif [[ "$arg" == "--reconfigure-lenas-vscode" ]]; then
    UBUNTU_SETUP_RECONFIGURE_LENAS_VSCODE=1
  elif [[ "$arg" == "--configure-gsettings" ]]; then
    UBUNTU_SETUP_CONFIGURE_GSETTINGS=1
  elif [[ "$arg" == "--configure-lenas-gsettings" ]]; then
    UBUNTU_SETUP_CONFIGURE_LENAS_GSETTINGS=1
  elif [[ "$arg" == "--install-local-ai" ]]; then
    UBUNTU_SETUP_INSTALL_LOCAL_AI=1
  elif [[ "$arg" == "--install-godot" ]]; then
    UBUNTU_SETUP_INSTALL_GODOT=1
  elif [[ "$arg" == "--install-openssh-server" ]]; then
    UBUNTU_SETUP_INSTALL_OPENSSH_SERVER=1
  else
    echo "Unknown argument: $arg"
    echo
    printHelpText
    exit 1
  fi
done

UBUNTU_SETUP_USERNAME=$(id -un)
UBUNTU_SETUP_USER_ID=$(id -u)
UBUNTU_SETUP_GROUP_ID=$(id -g)

if [[ -n "$BASH_VERSION" ]]; then
  echo "[UBUNTU SETUP] Script is running in Bash ($BASH_VERSION)."
else
  echo "[UBUNTU SETUP] Script is not running in Bash. Abort."
  exit 1
fi
if [ $EUID -eq 0 ]; then
  echo "[UBUNTU SETUP] This script is not intended to be run as root! Run as local user instead! Abort."
  exit 1
else
  echo "[UBUNTU SETUP] Running as user '${UBUNTU_SETUP_USERNAME:-}'."
fi
if [[ "$(lsb_release -si 2>/dev/null)" != "Ubuntu" ]]; then
  echo "[UBUNTU SETUP] Your linux distribution $(lsb_release -si 2>/dev/null) is not supported! Abort."
  exit 1
fi

UBUNTU_SETUP_DISTRO_VERSION=$(lsb_release -sr 2>/dev/null)

if [[ "$UBUNTU_SETUP_DISTRO_VERSION" != "24.04" ]] && [[ "$UBUNTU_SETUP_DISTRO_VERSION" != "26.04" ]]; then
  echo "[UBUNTU SETUP] Your Ubuntu version is not supported $UBUNTU_SETUP_DISTRO_VERSION! Abort."
  exit 1
else
  echo "[UBUNTU SETUP] Running on $(lsb_release -sd 2>/dev/null)."
fi

# ensure essentials are installed before running other installers
installEssentials

if [[ "${UBUNTU_SETUP_RECONFIGURE_GIT:-}" == "1" ]] || [[ "${UBUNTU_SETUP_RECONFIGURE_LENAS_GIT:-}" == "1" ]]; then
  reconfigureGit
fi

if [[ "${UBUNTU_SETUP_RECONFIGURE_VSCODE:-}" == "1" ]] || [[ "${UBUNTU_SETUP_RECONFIGURE_LENAS_VSCODE:-}" == "1" ]]; then
  reconfigureVsCode
fi

if [[ "${UBUNTU_SETUP_CONFIGURE_GSETTINGS:-}" == "1" ]] || [[ "${UBUNTU_SETUP_CONFIGURE_LENAS_GSETTINGS:-}" == "1" ]]; then
  configureGnomeSettings
fi

if [[ "${UBUNTU_SETUP_INSTALL_LOCAL_AI:-}" == "1" ]]; then
  if [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-local-ai is mutually exclusive with option --basic-setup"
    exit 1
  elif [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-local-ai is mutually exclusive with option --lenas-setup"
    exit 1
  else
    installNodeJs
    #installOpenCode
    installClaudeCode
    #installLlamaCpp
    #installOllama
  fi
fi

if [[ "${UBUNTU_SETUP_INSTALL_GODOT:-}" == "1" ]]; then
  if [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-godot is mutually exclusive with option --basic-setup"
    exit 1
  elif [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-godot is mutually exclusive with option --lenas-setup"
    exit 1
  else
    installGodot
  fi
fi

if [[ "${UBUNTU_SETUP_INSTALL_OPENSSH_SERVER:-}" == "1" ]]; then
  if [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-openssh-server is mutually exclusive with option --basic-setup"
    exit 1
  elif [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
    echo "Error: option --install-openssh-server is mutually exclusive with option --lenas-setup"
    exit 1
  else
    installOpenSshServer
  fi
fi

if [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]] && [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
  echo "Error: option --basic-setup is mutually exclusive with option --lenas-setup"
  exit 1
elif [[ "${UBUNTU_SETUP_BASIC_SETUP:-}" == "1" ]] || [[ "${UBUNTU_SETUP_LENAS_SETUP:-}" == "1" ]]; then
  startUbuntuSetup
fi
