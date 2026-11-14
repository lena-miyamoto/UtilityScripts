#!/bin/sh
set -eu

# 0. Pin PATH before any external helper runs, so a shim earlier on PATH cannot
#    redirect helper resolution. Keep only trusted system dirs, then add the
#    user's uv locations, resolved from the passwd database under that PATH.
PATH=/usr/bin:/bin
export PATH
HOST_HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
PATH="/usr/bin:/bin:/usr/local/bin:$HOST_HOME/.cargo/bin:$HOST_HOME/.local/bin"
export PATH

# 1. Resolve symlinks on $0 itself so an agent cannot symlink the script elsewhere
SCRIPT_PATH="$(readlink -f -- "$0")"
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

# 2. Require this exact project: both the Python project file and this repo's
#    entrypoint module must exist under the resolved project directory.
if [ ! -f "$REPO_ROOT/pyproject.toml" ] || [ ! -f "$REPO_ROOT/.claude/scripts/entrypoints.py" ]; then
  printf 'Error: %s is not the UtilityScripts project.\n' "$REPO_ROOT" >&2
  exit 1
fi

# 3. Resolve host binaries explicitly and require absolute, regular executables,
#    so a shim on PATH cannot redirect the sandbox launcher. Hardcode host paths
#    so an agent cannot inject UV_PYTHON_INSTALL_DIR to mount ~/.ssh.
BWRAP_BIN="$(command -v bwrap || true)"
UV_BIN="$(command -v uv || true)"
for binary in "$BWRAP_BIN" "$UV_BIN"; do
  case "$binary" in
  /*) ;;
  *)
    printf 'Error: a required binary is not on PATH.\n' >&2
    exit 1
    ;;
  esac
  if [ ! -f "$binary" ] || [ ! -x "$binary" ]; then
    printf 'Error: %s is not a regular executable.\n' "$binary" >&2
    exit 1
  fi
done
UV_BIN="$(readlink -f -- "$UV_BIN")"
UV_PYTHON_DIR="$HOST_HOME/.local/share/uv/python"

# 4. Target project. Without -C the repo root runs its `test` entry point; with
#    `-C DIR` a uv project under the repo runs plain pytest (its console script
#    only, no `test` entry point).
TARGET_DIR="$REPO_ROOT"
TEST_CMD="test"
if [ "${1:-}" = "-C" ]; then
  if [ $# -lt 2 ]; then
    printf 'Error: -C requires a project directory.\n' >&2
    exit 1
  fi
  shift
  case "$1" in
  /*) TARGET_DIR="$(cd -- "$1" && pwd -P)" ;;
  *) TARGET_DIR="$(cd -- "$REPO_ROOT/$1" && pwd -P)" ;;
  esac
  shift
  case "$TARGET_DIR" in
  "$REPO_ROOT" | "$REPO_ROOT"/*) ;;
  *)
    printf 'Error: %s is outside the repository.\n' "$TARGET_DIR" >&2
    exit 1
    ;;
  esac
  if [ ! -f "$TARGET_DIR/pyproject.toml" ]; then
    printf 'Error: %s has no pyproject.toml (not a uv project).\n' "$TARGET_DIR" >&2
    exit 1
  fi
  if [ "$TARGET_DIR" != "$REPO_ROOT" ]; then
    TEST_CMD="pytest"
  fi
fi

# 5. Block dangerous pytest plugin/config injection flags in "$@"
for arg in "$@"; do
  case "$arg" in
  -p | -p?* | -o | -o?* | -c | -c?* | --plugin* | --override-ini* | --config-file* | --rootdir*)
    printf 'Error: Forbidden pytest flag: %s\n' "$arg" >&2
    exit 1
    ;;
  [A-Za-z_]*=*)
    printf 'Error: Environment-assignment argument is not allowed: %s\n' "$arg" >&2
    exit 1
    ;;
  esac
done

# 6. Use env -i to strip all inherited host environment variables before starting bwrap
exec env -i PATH=/usr/bin:/bin "$BWRAP_BIN" \
  --unshare-all \
  --die-with-parent \
  --new-session \
  --clearenv \
  --ro-bind /usr /usr \
  --ro-bind /lib /lib \
  --ro-bind-try /lib64 /lib64 \
  --ro-bind /bin /bin \
  --ro-bind /sbin /sbin \
  --tmpfs /tmp \
  --dir /tmp/uv-bin \
  --ro-bind "$UV_BIN" /tmp/uv-bin/uv \
  --ro-bind-try "$UV_PYTHON_DIR" "$UV_PYTHON_DIR" \
  --ro-bind "$REPO_ROOT" "$REPO_ROOT" \
  --proc /proc \
  --dev /dev \
  --chdir "$TARGET_DIR" \
  --setenv HOME "$HOST_HOME" \
  --setenv PATH "/tmp/uv-bin:/usr/local/bin:/usr/bin:/bin" \
  --setenv UV_CACHE_DIR "/tmp/uv-cache" \
  --setenv UV_PYTHON_INSTALL_DIR "$UV_PYTHON_DIR" \
  --setenv PYTEST_ADDOPTS "-o cache_dir=/tmp/pytest-cache" \
  uv run --offline --no-sync "$TEST_CMD" "$@"
