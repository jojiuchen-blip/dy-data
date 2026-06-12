#!/usr/bin/env bash
set -eu

if [ -z "${VNC_PASSWORD:-}" ]; then
  echo "VNC_PASSWORD must be set" >&2
  exit 2
fi

mkdir -p "$HOME/Downloads" "$HOME/.config/chromium" "$HOME/.vnc"
x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1

rm -f /tmp/.X99-lock
rm -f \
  "$HOME/.config/chromium/SingletonCookie" \
  "$HOME/.config/chromium/SingletonLock" \
  "$HOME/.config/chromium/SingletonSocket"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -nolisten tcp >/tmp/xvfb.log 2>&1 &
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -rfbauth "$HOME/.vnc/passwd" -rfbport 5900 -localhost >/tmp/x11vnc.log 2>&1 &

chromium \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --user-data-dir="$HOME/.config/chromium" \
  --remote-debugging-address=0.0.0.0 \
  --remote-debugging-port="$CHROMIUM_REMOTE_DEBUGGING_PORT" \
  "$CHROMIUM_START_URL" >/tmp/chromium.log 2>&1 &

exec websockify --web=/usr/share/novnc/ "$NOVNC_PORT" localhost:5900
