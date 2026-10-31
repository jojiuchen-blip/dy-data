#!/usr/bin/env bash
set -eu

BROWSER_EXPORT_ACTIVE_DIR="/run/browser"

if [ "$(id -u)" = "0" ] && [ "${BROWSER_ENTRYPOINT_AS_BROWSER:-}" != "1" ]; then
  export HOME=/home/browser
  mkdir -p \
    "$HOME/Downloads" \
    "$HOME/.config/chromium" \
    "$HOME/.cache" \
    "$HOME/.vnc" \
    "$BROWSER_EXPORT_ACTIVE_DIR" \
    /tmp/chromium-crashes
  chown -R browser:browser \
    "$HOME/Downloads" \
    "$HOME/.config" \
    "$HOME/.cache" \
    "$HOME/.vnc" \
    /tmp/chromium-crashes
  chown browser:browser "$BROWSER_EXPORT_ACTIVE_DIR"
  chmod 1777 "$BROWSER_EXPORT_ACTIVE_DIR"
  export BROWSER_ENTRYPOINT_AS_BROWSER=1
  exec gosu browser "$0" "$@"
fi

if [ -z "${VNC_PASSWORD:-}" ]; then
  echo "VNC_PASSWORD must be set" >&2
  exit 2
fi

NOVNC_PORT="${PORT:-${NOVNC_PORT:-6080}}"
mkdir -p "$BROWSER_EXPORT_ACTIVE_DIR"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p \
  "$HOME/Downloads" \
  "$HOME/.vnc" \
  "$XDG_CONFIG_HOME/chromium" \
  "$XDG_CONFIG_HOME/chromium/Crash Reports" \
  "$XDG_CONFIG_HOME/chromium/Crashpad" \
  "$XDG_CACHE_HOME/chromium" \
  /tmp/chromium-crashes
x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1

# The runtime owns all desktop/CDP/Chromium processes and recovery state.
exec python3 /usr/local/bin/browser-runtime.py serve
