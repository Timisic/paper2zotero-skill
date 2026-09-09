#!/usr/bin/env bash
# Fetch the public repository and start its setup without a manual ZIP download.
set -euo pipefail
REPO='https://github.com/Timisic/paper2zotero-skill.git'
CHECKOUT="${PAPER2ZOTERO_SOURCE_DIR:-$HOME/.local/share/paper2zotero-source}"
case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo 'Windows 用户请使用 README 中的 PowerShell 安装命令。' >&2; exit 1 ;;
esac
if ! git --version >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then brew install git
      else
        xcode-select --install || true
        echo '请完成弹出的开发工具安装，然后重新运行本命令。'; exit 1
      fi ;;
    Linux)
      command -v apt-get >/dev/null 2>&1 || { echo '此 Linux 发行版请先安装 Git。'; exit 1; }
      elevate=(); if [[ "$EUID" != 0 ]]; then elevate=(sudo); fi
      "${elevate[@]}" apt-get update
      "${elevate[@]}" apt-get install -y git ca-certificates ;;
  esac
fi
if [[ -e "$CHECKOUT" ]]; then
  [[ -d "$CHECKOUT/.git" ]] || { echo '安装缓存被其他目录占用，已保留。'; exit 1; }
  [[ "$(git -C "$CHECKOUT" remote get-url origin)" == "$REPO" ]] || { echo '安装缓存来源不匹配，已保留。'; exit 1; }
  [[ -z "$(git -C "$CHECKOUT" status --porcelain)" ]] || { echo '安装缓存有本地改动，已保留；请处理后重跑。'; exit 1; }
  git -C "$CHECKOUT" pull --ff-only origin main
else
  mkdir -p "$(dirname "$CHECKOUT")"
  git clone --depth 1 --branch main "$REPO" "$CHECKOUT"
fi
# Preserve a terminal for the interactive Wizard even when this installer is piped.
if [[ -t 0 || "${1:-}" == --dependencies-only || "${1:-}" == --check ]]; then
  exec bash "$CHECKOUT/install/setup.sh" "$@"
elif [[ -r /dev/tty ]]; then
  exec bash "$CHECKOUT/install/setup.sh" "$@" </dev/tty
else
  echo "获取完成；请在终端运行：bash \"$CHECKOUT/install/setup.sh\""
  exit 2
fi
