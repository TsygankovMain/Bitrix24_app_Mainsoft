#!/bin/bash
set -e

# Turn color on
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Running migrations...${NC}"
python manage.py migrate --noinput

echo -e "${GREEN}Running migrations...${NC}"
python manage.py migrate --noinput

echo -e "${GREEN}Starting Uvicorn server...${NC}"
exec uvicorn asgi:application --host 0.0.0.0 --port 8000
