# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

# Install pinned pnpm without resolving latest during build
ARG PNPM_VERSION=9.15.9
RUN npm install -g pnpm@${PNPM_VERSION}

# Copy manifest files
COPY frontend/package.json frontend/.npmrc ./

# Install dependencies
RUN pnpm install --no-frozen-lockfile

# Copy source code
COPY frontend/ .

# Build static site (Nuxt generate)
# IMPORTANT: Must set app URL for build-time baking of runtimeConfig
ENV NUXT_PUBLIC_APP_URL="https://tsygankovmain-bitrix24-app-mainsoft-6536.twc1.net"
RUN pnpm run generate

# Stage 2: Final Backend Image
FROM python:3.11-slim

# Install system dependencies (curl for healthcheck, pg_client for db)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m appuser

WORKDIR /app

# Install Python dependencies
COPY backends/python/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn whitenoise

# Copy backend code
COPY backends/python/api/ /app/

# Copy built frontend assets from Stage 1
# We place them in static/frontend so whitenoise can find them (setup needed in settings.py)
COPY --from=frontend-builder /app/frontend/.output/public /app/frontend_build

# Copy and setup start script
RUN chmod +x /app/start.sh

# Switch to non-root user
USER appuser

# Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Entrypoint
CMD ["/app/start.sh"]
