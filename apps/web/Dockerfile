FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

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
    '        proxy_set_header Host api.railway.internal;' \
    '    }' \
    '    location / {' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '}' > /etc/nginx/templates/default.conf.template

EXPOSE 80
