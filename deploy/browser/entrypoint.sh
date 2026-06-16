#!/usr/bin/env bash
set -eu

if [ "$(id -u)" = "0" ] && [ "${BROWSER_ENTRYPOINT_AS_BROWSER:-}" != "1" ]; then
  export HOME=/home/browser
  mkdir -p \
    "$HOME/Downloads" \
    "$HOME/.config/chromium" \
    "$HOME/.cache" \
    "$HOME/.vnc" \
    /tmp/chromium-crashes
  chown -R browser:browser \
    "$HOME/Downloads" \
    "$HOME/.config" \
    "$HOME/.cache" \
    "$HOME/.vnc" \
    /tmp/chromium-crashes
  export BROWSER_ENTRYPOINT_AS_BROWSER=1
  exec gosu browser "$0" "$@"
fi

if [ -z "${VNC_PASSWORD:-}" ]; then
  echo "VNC_PASSWORD must be set" >&2
  exit 2
fi

NOVNC_PORT="${PORT:-${NOVNC_PORT:-6080}}"
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

python3 - "$CHROMIUM_REMOTE_DEBUGGING_PORT" "$CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT" <<'PY' >/tmp/cdp-proxy.log 2>&1 &
import socket
import socketserver
import sys
import threading


bind_port = int(sys.argv[1])
target_port = int(sys.argv[2])
target_authority = f"127.0.0.1:{target_port}".encode()


def rewrite_devtools_request(data):
    if b"\r\n\r\n" not in data:
        return data
    headers, body = data.split(b"\r\n\r\n", 1)
    rewritten = []
    for line in headers.split(b"\r\n"):
        lower = line.lower()
        if lower.startswith(b"host:"):
            rewritten.append(b"Host: " + target_authority)
        elif lower.startswith(b"origin:"):
            rewritten.append(b"Origin: http://" + target_authority)
        else:
            rewritten.append(line)
    return b"\r\n".join(rewritten) + b"\r\n\r\n" + body


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = socket.create_connection(("127.0.0.1", target_port))

        def pipe(src, dst, rewrite_first=False):
            first_chunk = True
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    if rewrite_first and first_chunk:
                        while b"\r\n\r\n" not in data:
                            next_chunk = src.recv(65536)
                            if not next_chunk:
                                break
                            data += next_chunk
                        data = rewrite_devtools_request(data)
                        first_chunk = False
                    dst.sendall(data)
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        client_to_upstream = threading.Thread(target=pipe, args=(self.request, upstream, True), daemon=True)
        client_to_upstream.start()
        pipe(upstream, self.request)


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


with ThreadingTCPServer(("0.0.0.0", bind_port), ProxyHandler) as server:
    server.serve_forever()
PY

rm -f /tmp/.X99-lock
rm -f \
  "$XDG_CONFIG_HOME/chromium/SingletonCookie" \
  "$XDG_CONFIG_HOME/chromium/SingletonLock" \
  "$XDG_CONFIG_HOME/chromium/SingletonSocket"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -nolisten tcp >/tmp/xvfb.log 2>&1 &
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -rfbauth "$HOME/.vnc/passwd" -rfbport 5900 -localhost >/tmp/x11vnc.log 2>&1 &

display_number="${DISPLAY#:}"
for attempt in $(seq 1 30); do
  if [ -S "/tmp/.X11-unix/X${display_number}" ]; then
    break
  fi
  sleep 1
done

chromium \
  --no-first-run \
  --no-default-browser-check \
  --disable-breakpad \
  --disable-crash-reporter \
  --disable-dev-shm-usage \
  --no-sandbox \
  --crash-dumps-dir=/tmp/chromium-crashes \
  --user-data-dir="$XDG_CONFIG_HOME/chromium" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT" \
  "$CHROMIUM_START_URL" >/tmp/chromium.log 2>&1 &
chromium_pid="$!"
echo "chromium_pid=${chromium_pid} cdp_port=${CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT}"

if [ "${BROWSER_EXPORT_SCHEDULER_ENABLED:-false}" = "true" ]; then
  if [ -z "${DATABASE_URL:-${DY_DATABASE_URL:-}}" ]; then
    echo "BROWSER_EXPORT_SCHEDULER_ENABLED is true, but DATABASE_URL/DY_DATABASE_URL is not set" >&2
  else
    (
      delay="${BROWSER_EXPORT_START_DELAY_SECONDS:-60}"
      interval="${BROWSER_EXPORT_INTERVAL_SECONDS:-86400}"
      echo "scheduler_enabled delay=${delay}s interval=${interval}s"
      sleep "$delay"
      while true; do
        echo "run_start $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        if ! kill -0 "$chromium_pid" 2>/dev/null; then
          echo "chromium_not_running status_unknown"
          tail -n 120 /tmp/chromium.log || true
        fi
        if BROWSER_CDP_URL="http://127.0.0.1:${CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT}" \
          WORKER_MODE=browser_export_only \
          WORKER_RUN_ONCE=true \
          WORKER_RUN_ON_START=true \
          python3 -m apps.worker.scheduler; then
          echo "run_done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        else
          status="$?"
          echo "run_failed status=${status} $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          echo "--- chromium.log tail ---"
          tail -n 160 /tmp/chromium.log || true
          echo "--- cdp-proxy.log tail ---"
          tail -n 160 /tmp/cdp-proxy.log || true
        fi
        sleep "$interval"
      done
    ) 2>&1 | sed -u 's/^/[browser-export] /' &
  fi
fi

exec websockify --web=/usr/share/novnc/ "0.0.0.0:${NOVNC_PORT}" localhost:5900
