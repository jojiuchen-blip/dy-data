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
    'limit_req_zone $binary_remote_addr zone=oauth_write_per_ip:10m rate=10r/m;' \
    'limit_req_zone $binary_remote_addr zone=mcp_per_ip:10m rate=60r/m;' \
    'server {' \
    '    listen 80;' \
    '    server_name _;' \
    '    root /usr/share/nginx/html;' \
    '    index index.html;' \
    '    limit_req_status 429;' \
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
    '    location = /mcp {' \
    '        client_max_body_size 1m;' \
    '        limit_req zone=mcp_per_ip burst=30 nodelay;' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /authorize {' \
    '        client_max_body_size 16k;' \
    '        limit_req zone=oauth_write_per_ip burst=5 nodelay;' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /register {' \
    '        client_max_body_size 16k;' \
    '        limit_req zone=oauth_write_per_ip burst=5 nodelay;' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /token {' \
    '        client_max_body_size 16k;' \
    '        limit_req zone=oauth_write_per_ip burst=5 nodelay;' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /revoke {' \
    '        client_max_body_size 16k;' \
    '        limit_req zone=oauth_write_per_ip burst=5 nodelay;' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /agent.md {' \
    '        proxy_pass ${API_UPSTREAM};' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_read_timeout 300s;' \
    '        proxy_buffering off;' \
    '    }' \
    '    location = /agent/SKILL.md {' \
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
