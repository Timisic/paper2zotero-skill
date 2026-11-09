#!/usr/bin/env bash
# One entry point: bootstrap dependencies, install the skill, collect credentials.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: bash setup.sh [--dependencies-only | --check | --runtime-only | --modules [module ...]]'
  echo 'Default: install dependencies and skill, then configure services interactively.'
  exit 0
fi
case "${1:-}" in ''|--dependencies-only|--check|--runtime-only|--modules) ;; *) echo 'Unknown option; use --help' >&2; exit 2;; esac
prefix_path="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
export PATH="$prefix_path:$PATH"
SYSTEM="$(uname -s)"
case "$SYSTEM" in
  Darwin) echo '系统：macOS（Homebrew）' ;;
  Linux) echo '系统：Linux / WSL（apt）' ;;
  MINGW*|MSYS*|CYGWIN*) echo 'Windows 请双击 install\setup.cmd。' >&2; exit 1 ;;
  *) echo "暂不支持的系统：$SYSTEM" >&2; exit 1 ;;
esac
BUNDLED=''
for candidate in "$SKILL_DIR/../runtime/python/bin/python3"; do
  if [[ -f "$candidate" ]]; then BUNDLED="$candidate"; break; fi
done
if [[ -n "$BUNDLED" ]]; then
  echo '离线安装包：使用随附的 Python，不联网安装 Python 或 Git。'
  # Unzip tools that drop permissions or add quarantine would block the bundled interpreter.
  chmod +x "$BUNDLED" 2>/dev/null || true
  if [[ "$SYSTEM" == Darwin ]]; then xattr -dr com.apple.quarantine "$SKILL_DIR/../runtime" 2>/dev/null || true; fi
  PYTHON_BIN="$BUNDLED"
fi
find_python() {
  local candidate
  for candidate in "${PYTHON_BIN:-python3}" python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,11))' 2>/dev/null; then
      PYTHON_BIN="$(command -v "$candidate")"; return 0
    fi
  done
  return 1
}
if [[ "${1:-}" == --modules ]]; then echo '准备：查找 Python 3.11+'; else echo '[1/3] 检查本地依赖'; fi
python_ready=0
if find_python; then
  python_ready=1
  echo "✓ Python 3.11+ 可用：${PYTHON_BIN}（跳过安装）"
else
  echo '待安装：Python 3.11+'
fi
if [[ "${1:-}" == --check ]]; then
  find_python || { echo 'Python 缺失，请运行 setup.sh'; exit 1; }
  check_args=(--check)
  if [[ "${2:-}" == --group ]]; then check_args+=(--group); fi
  export PYTHON_BIN
  exec bash "$SKILL_DIR/scripts/run-python.sh" "$SKILL_DIR/scripts/configure.py" "${check_args[@]}"
fi
if [[ "$python_ready" != 1 ]]; then
  echo '正在安装 Python；系统可能要求管理员密码。'
  case "$(uname -s)" in
    Darwin)
      if ! command -v brew >/dev/null 2>&1; then
        installer="$(mktemp)"
        trap 'rm -f "$installer"' EXIT
        curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
        /bin/bash "$installer"
      fi
      brew install python@3.13
      ;;
    Linux)
      if ! command -v apt-get >/dev/null 2>&1; then
        echo '自动安装支持 macOS、Debian 12+/Ubuntu 24.04+（含 WSL）；此系统暂不支持。' >&2; exit 1
      else
        elevate=()
        if [[ "$EUID" != 0 ]]; then elevate=(sudo); fi
        "${elevate[@]}" apt-get update || true
        "${elevate[@]}" apt-get install -y ca-certificates python3 python3-venv
      fi
      ;;
    *) echo '请在 macOS 或 Debian/Ubuntu（含 WSL）运行 setup。' >&2; exit 1 ;;
  esac
fi
find_python || { echo '系统仓库没有 Python 3.11+；请升级到 Debian 12+/Ubuntu 24.04+ 后重试。' >&2; exit 1; }
if [[ "${1:-}" == --modules ]]; then exec "$PYTHON_BIN" "$SKILL_DIR/scripts/modules.py" "${@:2}"; fi
echo '[2/3] 准备独立运行环境（scansci-pdf、markitdown），首次可能需要几分钟'
"$PYTHON_BIN" -c '
import sys
sys.path.insert(0, sys.argv[1])
from setup_connection import ensure_default_tools
try:
    print(f"✓ 运行环境：{ensure_default_tools()}")
except ValueError as error:
    sys.exit(str(error))' "$SKILL_DIR/scripts"
if [[ "${1:-}" == --runtime-only ]]; then exit 0; fi
export PYTHON_BIN
bash "$SKILL_DIR/scripts/install-skill.sh"
echo '依赖和 skill 已安装；运行 setup.sh 继续配置。'
