#!/usr/bin/env bash
# One entry point: bootstrap dependencies, install the skill, collect credentials.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: bash setup.sh [--dependencies-only | --check | --probe | --runtime-only]'
  echo 'Default: install dependencies and skill, then configure services interactively.'
  exit 0
fi
case "${1:-}" in ''|--dependencies-only|--check|--probe|--runtime-only) ;; *) echo 'Unknown option; use --help' >&2; exit 2;; esac
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
SYSTEM="$(uname -s)"
case "$SYSTEM" in
  Darwin) echo '系统：macOS（Homebrew）' ;;
  Linux) echo '系统：Linux / WSL（apt）' ;;
  MINGW*|MSYS*|CYGWIN*)
    echo '系统：Windows（原生 Python / Poppler）'
    if [[ -n "${PYTHON_BIN:-}" ]]; then PYTHON_BIN="$(cygpath -u "$PYTHON_BIN")"; fi
    ;;
  *) echo "暂不支持的系统：$SYSTEM" >&2; exit 1 ;;
esac
find_python() {
  local candidate
  for candidate in "${PYTHON_BIN:-python3}" python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,11))' 2>/dev/null; then
      PYTHON_BIN="$(command -v "$candidate")"; return 0
    fi
  done
  return 1
}
echo '[1/3] 检查本地依赖'
python_ready=0
pdf_ready=0
if find_python; then
  python_ready=1
  echo "✓ Python 3.11+ 可用：${PYTHON_BIN}（跳过安装）"
else
  echo '待安装：Python 3.11+'
fi
if command -v pdftotext >/dev/null 2>&1 && pdftotext -v >/dev/null 2>&1; then
  pdf_ready=1
  echo "✓ Poppler 可运行：$(command -v pdftotext)（跳过安装）"
else
  echo '待安装或修复：Poppler'
fi
if [[ "${1:-}" == --probe ]]; then exit 0; fi
if [[ "${1:-}" == --check ]]; then
  find_python || { echo 'Python 缺失，请运行 setup.sh'; exit 1; }
  exec "$PYTHON_BIN" "$SKILL_DIR/scripts/configure.py" --check
fi
if [[ "$python_ready" != 1 || "$pdf_ready" != 1 ]]; then
  echo '正在安装运行依赖（Python、PDF 文本工具）；系统可能要求管理员密码。'
  case "$(uname -s)" in
    Darwin)
      if ! command -v brew >/dev/null 2>&1; then
        installer="$(mktemp)"
        trap 'rm -f "$installer"' EXIT
        curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
        /bin/bash "$installer"
      fi
      packages=()
      find_python || packages+=(python@3.13)
      [[ "$pdf_ready" == 1 ]] || packages+=(poppler)
      if (( ${#packages[@]} )); then brew install "${packages[@]}"; fi
      ;;
    Linux)
      if ! command -v apt-get >/dev/null 2>&1; then
        echo '自动安装支持 macOS、Debian 12+/Ubuntu 24.04+（含 WSL）；此系统暂不支持。' >&2; exit 1
      fi
      elevate=()
      if [[ "$EUID" != 0 ]]; then elevate=(sudo); fi
      "${elevate[@]}" apt-get update
      packages=(ca-certificates)
      [[ "$python_ready" == 1 ]] || packages+=(python3)
      [[ "$pdf_ready" == 1 ]] || packages+=(poppler-utils)
      "${elevate[@]}" apt-get install -y "${packages[@]}"
      ;;
    MINGW*|MSYS*|CYGWIN*) echo '请双击 setup.cmd，自动安装缺少的 Windows 工具。' >&2; exit 1 ;;
    *) echo '请在 macOS 或 Debian/Ubuntu（含 WSL）运行 setup。' >&2; exit 1 ;;
  esac
fi
find_python || { echo '系统仓库没有 Python 3.11+；请升级到 Debian 12+/Ubuntu 24.04+ 后重试。' >&2; exit 1; }
pdftotext -v >/dev/null 2>&1 || { echo 'PDF 工具安装未成功，请重跑 setup。' >&2; exit 1; }
echo '[2/3] 保存运行工具的位置'
# Persist the interpreter choice without requiring shell profile changes.
mkdir -p "$HOME/.config/literature-to-zotero"
interpreter_path="$PYTHON_BIN"
if [[ "$SYSTEM" == MINGW* || "$SYSTEM" == MSYS* || "$SYSTEM" == CYGWIN* ]]; then interpreter_path="$(cygpath -w "$PYTHON_BIN")"; fi
printf '%s\n' "$interpreter_path" > "$HOME/.config/literature-to-zotero/python-path"
pdf_directory="$(dirname "$(command -v pdftotext)")"
if [[ "$SYSTEM" == MINGW* || "$SYSTEM" == MSYS* || "$SYSTEM" == CYGWIN* ]]; then pdf_directory="$(cygpath -w "$pdf_directory")"; fi
printf '%s\n' "$pdf_directory" > "$HOME/.config/literature-to-zotero/pdf-bin"
if [[ "${1:-}" == --runtime-only ]]; then exit 0; fi
export PYTHON_BIN
bash "$SKILL_DIR/scripts/install-skill.sh"
echo '依赖和 skill 已安装；运行 setup.sh 继续配置。'
