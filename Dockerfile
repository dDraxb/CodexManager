# syntax=docker/dockerfile:1

FROM node:25-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN sh -lc 'for i in 1 2 3; do npm ci && exit 0; echo "npm ci failed, retry $i/3"; sleep 3; done; exit 1'
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CODEXMGR_HOME=/data \
    CODEXMGR_UI_HOST=0.0.0.0 \
    CODEXMGR_UI_PORT=8790

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git tmux curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN pip install --no-cache-dir /app/backend

VOLUME ["/data"]
EXPOSE 8790

CMD ["codexmgr", "ui", "--host", "0.0.0.0", "--port", "8790"]
