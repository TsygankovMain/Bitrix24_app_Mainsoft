#!/bin/bash
set -e

# Turn color on
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Skipping automatic migrations at runtime...${NC}"
echo "DB Config: HOST=$DB_HOST, PORT=$DB_PORT, NAME=$DB_NAME, USER=$DB_USER"
echo "Run 'python manage.py migrate --noinput' as a release step before starting the app."

echo -e "${GREEN}Collecting static files...${NC}"
python manage.py collectstatic --noinput || echo "ERROR: collectstatic failed. Continuing..."

echo -e "${GREEN}Starting Uvicorn server...${NC}"
exec uvicorn asgi:application --host 0.0.0.0 --port 8000
