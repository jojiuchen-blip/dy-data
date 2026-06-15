FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i \
    -e 's|http://deb.debian.org/debian-security|http://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
    -e 's|http://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' \
    /etc/apt/sources.list.d/debian.sources

RUN set -eux; \
    for attempt in 1 2 3 4 5; do \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            -o Acquire::Retries=5 \
            ca-certificates \
            chromium \
            chromium-sandbox \
            dumb-init \
            fluxbox \
            fonts-noto-cjk \
            novnc \
            websockify \
            x11vnc \
            xvfb \
        && break; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        apt-get clean; \
        rm -rf /var/lib/apt/lists/*; \
        sleep $((attempt * 5)); \
    done; \
    rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash browser \
    && mkdir -p /home/browser/Downloads /home/browser/.config/chromium /home/browser/.vnc \
    && chown -R browser:browser /home/browser

COPY entrypoint.sh /usr/local/bin/browser-entrypoint.sh

RUN sed -i 's/\r$//' /usr/local/bin/browser-entrypoint.sh \
    && chmod +x /usr/local/bin/browser-entrypoint.sh

USER browser
WORKDIR /home/browser

ENV DISPLAY=:99
ENV NOVNC_PORT=6080
ENV CHROMIUM_REMOTE_DEBUGGING_PORT=9222
ENV CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT=9223
ENV CHROMIUM_START_URL=https://life.douyin.com/
ENV SCREEN_WIDTH=1440
ENV SCREEN_HEIGHT=1000

EXPOSE 6080 9222

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/usr/local/bin/browser-entrypoint.sh"]
