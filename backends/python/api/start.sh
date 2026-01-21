#!/bin/bash
set -e

# Turn color on
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Running migrations...${NC}"
echo "DB Config: HOST=$DB_HOST, PORT=$DB_PORT, NAME=$DB_NAME, USER=$DB_USER"
# Attempt migration but don't fail the build if it fails (to allow debugging logs)
python manage.py migrate --noinput || echo "ERROR: Migrations failed. Continuing to start server for debugging..."



echo -e "${GREEN}Starting Uvicorn server...${NC}"
exec uvicorn asgi:application --host 0.0.0.0 --port 8000
