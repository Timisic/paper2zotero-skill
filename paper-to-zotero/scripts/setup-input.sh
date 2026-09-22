#!/usr/bin/env bash
# Setup-specific input; keep the shared wizard template unchanged.
authorization_has_controls() {
  local LC_ALL=C
  [[ "$1" =~ [[:cntrl:]] ]]
}

retry_connection() {
  local choice
  while true; do
    printf '  输入 1 重新粘贴或重试连接；输入 2 或直接回车，稍后再配置：'
    IFS= read -r choice || { printf '\n'; exit 130; }
    case "$choice" in
      1) return 0 ;;
      2|'') return 1 ;;
      *) note '请输入 1 或 2。' ;;
    esac
  done
}

read_authorization_line() (
  # Keep echo off between character reads as well as during each read.
  # A subshell owns these traps; the parent wizard's demo cleanup is untouched.
  local value='' char saved_tty=''
  trap 'if [[ -n "$saved_tty" ]]; then stty "$saved_tty" 2>/dev/null || true; fi' EXIT
  trap 'exit 130' INT TERM
  # This reader is called in an if-condition, so Bash's errexit is disabled.
  # Stop explicitly if we cannot save the terminal state or disable echo.
  if [[ -t 0 ]]; then
    saved_tty=$(stty -g) || exit 1
    stty -echo || exit 1
  fi
  while true; do
    IFS= read -r -s -n 1 char || exit 130
    case "$char" in
      ''|$'\r') break ;;
      $'\x7f'|$'\b')
        if [[ -n "$value" ]]; then
          value="${value%?}"
          [[ -n "$value" ]] || printf '\b\b\b\b\b\b      \b\b\b\b\b\b' >&2
        fi ;;
      *)
        [[ -n "$value" ]] || printf '******' >&2
        value+="$char" ;;
    esac
  done
  printf '%s' "$value"
)

ask_authorization() {
  local key="$1" prompt="$2" current value
  current=$(_existing "$key" || true)
  if authorization_has_controls "$current"; then
    warn '之前的输入没有正确粘贴，请重新复制网页上的完整授权码。'
    current=''
  fi
  if [[ "${WINDOWS:-0}" == 1 ]]; then
    note '复制网页上的完整授权码，按 Ctrl+V 粘贴（也可用 Shift+Insert），再按回车。'
  else
    note '复制网页上的完整授权码，使用终端的粘贴功能，再按回车。'
  fi
  note '收到输入会显示 ******，不会显示授权码内容。'
  while true; do
    value=''
    printf '  %s ' "$prompt"
    [[ -z "$current" ]] || printf '[回车保留已有授权] '
    if ! value="$(read_authorization_line)"; then
      printf '\n'
      note '配置已暂停，已保存内容保留。'
      exit 130
    fi
    printf '\n'
    if authorization_has_controls "$value"; then
      warn '没有收到完整授权码，这次输入未保存。请重新复制，用 Shift+Insert 或右键菜单“粘贴”，再按回车。'
      continue
    fi
    # Copying from a webpage often includes harmless surrounding spaces.
    value="${value#"${value%%[! ]*}"}"
    value="${value%"${value##*[! ]}"}"
    if [[ -z "$value" ]]; then
      value="$current"
      if [[ -n "$value" ]]; then note '已保留已有授权。'; else note '已跳过，之后可以继续配置。'; fi
    else
      note '已收到授权码，继续检查连接。'
    fi
    printf -v "$key" '%s' "$value"
    return 0
  done
}
