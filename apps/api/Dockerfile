FROM python:3.12-slim

ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/apps/api
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ] && [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn dy_api.main:app --host ${UVICORN_HOST:-0.0.0.0} --port ${PORT:-8000}"]
