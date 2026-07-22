FROM node:22-alpine AS build

ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

WORKDIR /app

COPY package*.json ./
RUN npm ci --registry=${NPM_CONFIG_REGISTRY}

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

ENV API_UPSTREAM=http://api.railway.internal:8000

RUN mkdir -p /etc/nginx/templates \
    && printf '%s\n' \
    'server {' \
    '    listen 80;' \
    '    server_name _;' \
    '    root /usr/share/nginx/html;' \
    '    index index.html;' \
    '    location /api/v1/ {' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_connect_timeout 5s;' \
    '        proxy_send_timeout 30s;' \
    '        proxy_read_timeout 30s;' \
    '    }' \
    '    location ^~ /.well-known/ {' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location ~ ^/(?:mcp|authorize|register|token|revoke|agent\.md|agent/SKILL\.md)$ {' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location / {' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '}' > /etc/nginx/templates/default.conf.template

EXPOSE 80
