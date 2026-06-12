FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        dumb-init \
        fluxbox \
        fonts-noto-cjk \
        novnc \
        websockify \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash browser \
    && mkdir -p /home/browser/Downloads /home/browser/.config/chromium /home/browser/.vnc \
    && chown -R browser:browser /home/browser

COPY entrypoint.sh /usr/local/bin/browser-entrypoint.sh

RUN chmod +x /usr/local/bin/browser-entrypoint.sh

USER browser
WORKDIR /home/browser

ENV DISPLAY=:99
ENV NOVNC_PORT=6080
ENV CHROMIUM_REMOTE_DEBUGGING_PORT=9222
ENV CHROMIUM_START_URL=https://life.douyin.com/
ENV SCREEN_WIDTH=1440
ENV SCREEN_HEIGHT=1000

EXPOSE 6080 9222

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/usr/local/bin/browser-entrypoint.sh"]
