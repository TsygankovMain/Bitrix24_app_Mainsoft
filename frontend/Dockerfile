# Dev stage
FROM node:20-slim AS dev
RUN apt-get update && apt-get install -y openssl
WORKDIR /app
ARG PNPM_VERSION=9.15.9
RUN npm install -g pnpm@${PNPM_VERSION}
# Note: Code will be mounted as volume in dev mode
# No COPY . ./ here to avoid overwriting mounted volume
EXPOSE 3000
CMD ["sh", "-c", "pnpm install --no-frozen-lockfile \
  && pnpm run dev"]

# Build stage
FROM node:20-alpine AS builder
RUN apk add --no-cache openssl
WORKDIR /app
ARG PNPM_VERSION=9.15.9
RUN npm install -g pnpm@${PNPM_VERSION}
COPY .npmrc package.json ./
RUN pnpm install --no-frozen-lockfile
COPY . ./
RUN pnpm run build

# Production stage
FROM node:20-alpine AS production
WORKDIR /app
COPY --from=builder /app/.output ./
COPY --from=builder /app/package*.json ./
EXPOSE 80
CMD ["node", "/app/server/index.mjs"]
