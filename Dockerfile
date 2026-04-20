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
# Production URLs are baked into the generated frontend, so the host
# must be supplied at build time for every release.
ARG VIRTUAL_HOST=""
ARG NUXT_PUBLIC_API_URL=""
ENV VIRTUAL_HOST=${VIRTUAL_HOST}
ENV NUXT_PUBLIC_APP_URL=${VIRTUAL_HOST}
ENV NUXT_PUBLIC_API_URL=${NUXT_PUBLIC_API_URL}
# Nuxt 4 + Vite 7 SSG build spikes >1.7GB heap during the "transforming" stage
# with ~1100 node_modules packages. Without this override Node is killed silently
# (SIGKILL from OOM) and the deploy log just cuts off mid-build.
ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN if [ -z "$VIRTUAL_HOST" ]; then echo "VIRTUAL_HOST build arg is required"; exit 1; fi \
    && case "$VIRTUAL_HOST" in http://*|https://*) NORMALIZED_HOST="$VIRTUAL_HOST" ;; *) NORMALIZED_HOST="https://$VIRTUAL_HOST" ;; esac \
    && export NUXT_PUBLIC_APP_URL="$NORMALIZED_HOST" \
    && export NUXT_PUBLIC_API_URL="${NUXT_PUBLIC_API_URL:-$NORMALIZED_HOST}" \
    && pnpm run generate

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
ARG VIRTUAL_HOST=""
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_TARGET=production
ENV VIRTUAL_HOST=${VIRTUAL_HOST}

# Entrypoint
CMD ["/app/start.sh"]
