.PHONY: help create-version delete-version dev-front dev-python prod-python status ps down down-all clean logs logs-nginxproxy security-scan security-tests db-backup db-restore

# Variables
DOCKER_COMPOSE = docker-compose
CURRENT_UID := $(shell id -u):$(shell id -g)

# Default target - show help
help: ## Show this help message
	@echo "🚀 Учёт трудозатрат — доступные команды"
	@echo "======================================"
	@echo ""
	@echo "📋 Версии проекта:"
	@echo "  create-version    Clone current project into versions/<name>"
	@echo "  delete-version    Remove versions/<name>"
	@echo ""
	@echo "🛠  Разработка:"
	@echo "  dev-front         Start frontend only"
	@echo "  dev-python        Start frontend + Django backend (local dev)"
	@echo ""
	@echo "🚀 Production:"
	@echo "  prod-python       Start production compose profile"
	@echo "                    (канонический релиз — сборка Dockerfile, см. DEPLOY_README.md)"
	@echo ""
	@echo "🔍 Мониторинг:"
	@echo "  status            Show Docker stats"
	@echo "  ps                Watch Docker processes"
	@echo "  logs              Show all container logs"
	@echo ""
	@echo "🧹 Очистка:"
	@echo "  down              Stop all containers and remove orphans"
	@echo "  clean             Complete Docker cleanup (containers, networks, volumes)"
	@echo "  down-all          Stop all containers including server compose"
	@echo ""
	@echo "🛡  Безопасность:"
	@echo "  security-scan     Run dependency vulnerability audit"
	@echo "  security-tests    Run orchestrated security test suite"
	@echo ""
	@echo "🗄  База данных:"
	@echo "  db-backup         Dump database to backup_<timestamp>.sql"
	@echo "  db-restore        Restore database from file=<path>"
	@echo ""
	@echo "🧪 Тесты:"
	@echo "  test-backend      Run Django test suite"
	@echo "  test-standalone   Run standalone (stubbed) backend checks"
	@echo "  test-frontend     Run frontend unit tests"
	@echo ""
	@echo "💡 Быстрый старт: make dev-python"
	@echo ""

.DEFAULT_GOAL := help

create-version:
	@echo "📂 Creating a new project version..."
	@./scripts/create-version.sh $(VERSION)

delete-version:
	@echo "🗑 Removing a project version..."
	@./scripts/delete-version.sh $(VERSION)

# Development
dev-front:
	@echo "Starting frontend"
	COMPOSE_PROFILES=frontend,cloudpub $(DOCKER_COMPOSE) --env-file .env up --build

dev-python:
	@echo "Starting dev python"
	@DB_TYPE_VALUE=$$(grep -E '^DB_TYPE=' .env 2>/dev/null | tail -n1 | cut -d= -f2); \
	if [ -z "$$DB_TYPE_VALUE" ]; then DB_TYPE_VALUE=postgresql; fi; \
	if [ "$$DB_TYPE_VALUE" = "mysql" ]; then DB_PROFILE="db-mysql"; else DB_PROFILE="db-postgres"; fi; \
	COMPOSE_PROFILES="frontend,python,cloudpub,$$DB_PROFILE" $(DOCKER_COMPOSE) --env-file .env up --build

# Production
prod-python:
	@echo "Starting prod python environment"
	COMPOSE_PROFILES=python FRONTEND_TARGET=production $(DOCKER_COMPOSE) up --build -d

# Tests
.PHONY: test-backend
test-backend:
	cd backends/python/api && python manage.py test main --settings=test_settings

# Автономные проверки: подменяют sys.modules заглушками, поэтому Django их не
# подхватывает (имя не совпадает с маской test*.py) и запускать их можно только
# по одному — иначе заглушки одного модуля протекают в следующий.
.PHONY: test-standalone
test-standalone:
	@cd backends/python/api && for m in $$(ls main/standalone_check_*.py | xargs -n1 basename | sed 's/\.py$$//'); do \
	  echo "--- $$m"; \
	  python -m unittest main.$$m || exit 1; \
	done

.PHONY: test-frontend
test-frontend:
	cd frontend && pnpm test

.PHONY: security-scan
security-scan:
	@./scripts/security-scan.sh

.PHONY: security-tests
security-tests:
	@./scripts/security-tests.sh $(SECURITY_TESTS_ARGS)

# Utils
status:
	docker stats

ps:
	watch -n 2 docker ps

down:
	@echo "🛑 Останавливаем все контейнеры..."
	COMPOSE_PROFILES=frontend,python,cloudpub $(DOCKER_COMPOSE) down --remove-orphans || true
	docker container stop $$(docker container ls -q --filter "name=b24" --filter "name=frontend" --filter "name=api" --filter "name=cloudpub") 2>/dev/null || true

down-all:
	$(DOCKER_COMPOSE) down --remove-orphans
	$(DOCKER_COMPOSE) -f docker-compose.server.yml down --remove-orphans

clean:
	@echo "🧹 Полная очистка Docker окружения..."
	$(DOCKER_COMPOSE) down --remove-orphans --volumes || true
	docker container rm -f $$(docker container ls -aq --filter "name=b24") 2>/dev/null || true
	docker network prune -f
	docker volume prune -f
	@echo "✓ Очистка завершена"

logs:
	$(DOCKER_COMPOSE) logs -f

logs-nginxproxy:
	$(DOCKER_COMPOSE) logs -f docker-compose.server.yml

# Database operations
db-backup:
	@DB_TYPE_VALUE=$$(grep -E '^DB_TYPE=' .env 2>/dev/null | tail -n1 | cut -d= -f2); \
	if [ -z "$$DB_TYPE_VALUE" ]; then DB_TYPE_VALUE=postgresql; fi; \
	if [ "$$DB_TYPE_VALUE" = "mysql" ]; then \
	  COMPOSE_PROFILES=db-mysql $(DOCKER_COMPOSE) exec -T database-mysql sh -lc "exec mysqldump -u\"$${DB_USER:-appuser}\" -p\"$${DB_PASSWORD:-apppass}\" \"$${DB_NAME:-appdb}\"" > backup_$(shell date +%Y%m%d_%H%M%S).sql; \
	else \
	  COMPOSE_PROFILES=db-postgres $(DOCKER_COMPOSE) exec -T database-postgres pg_dump -U $${DB_USER:-appuser} $${DB_NAME:-appdb} > backup_$(shell date +%Y%m%d_%H%M%S).sql; \
	fi

db-restore:
	@DB_TYPE_VALUE=$$(grep -E '^DB_TYPE=' .env 2>/dev/null | tail -n1 | cut -d= -f2); \
	if [ -z "$$DB_TYPE_VALUE" ]; then DB_TYPE_VALUE=postgresql; fi; \
	if [ "$$DB_TYPE_VALUE" = "mysql" ]; then \
	  COMPOSE_PROFILES=db-mysql $(DOCKER_COMPOSE) exec -T database-mysql sh -lc "exec mysql -u\"$${DB_USER:-appuser}\" -p\"$${DB_PASSWORD:-apppass}\" \"$${DB_NAME:-appdb}\"" < $(file); \
	else \
	  COMPOSE_PROFILES=db-postgres $(DOCKER_COMPOSE) exec -T database-postgres psql -U $${DB_USER:-appuser} $${DB_NAME:-appdb} < $(file); \
	fi
