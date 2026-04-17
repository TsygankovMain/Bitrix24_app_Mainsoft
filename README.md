# Учёт трудозатрат для Bitrix24

Приложение для Bitrix24 на связке `Nuxt 4 + Django + PostgreSQL`. Оно решает две задачи:

- учет времени прямо внутри карточки задачи;
- управленческая отчетность по сотрудникам, проектам и качеству учета.

## Что входит в продукт

- вкладка учета времени в задаче Bitrix24;
- хранение записей в CRM смарт-процессе;
- проектный контур с Project SPA / board;
- отчеты по сотрудникам, проектам, ежедневной нагрузке, дисциплине, потерям выручки и фокусу;
- экран настроек с маппингом полей, созданием СП и служебной диагностикой.

## Текущая production-модель

Production больше не должен опираться на CloudPub.

Канонический release path:

1. frontend собирается статически из `frontend/`;
2. артефакты фронта копируются в единый backend image;
3. Django отдает и `API`, и собранный SPA с одного production-домена;
4. этот же домен указывается в настройках Bitrix24-приложения.

Файл production-сборки:

- [Dockerfile](./Dockerfile)

## Local dev-модель

Локальная разработка по-прежнему может использовать tunnel, но это только dev-контур:

- `local-dev.yaml`
- `make dev-python`
- внешний tunnel/CloudPub нужен только чтобы открыть локальную версию внутри Bitrix24.

CloudPub не считается production-инфраструктурой и не должен фигурировать в release-настройках.

## Быстрый старт для локальной разработки

1. Создайте локальный env:

```bash
cp .env.example .env
```

2. Заполните минимум:

- `CLIENT_ID`
- `CLIENT_SECRET`
- `JWT_SECRET`
- `VIRTUAL_HOST`
- `DB_*`

3. Поднимите dev-окружение:

```bash
make dev-python
```

4. Для локального Bitrix24-приложения используйте:

- URL приложения: `https://ваш-внешний-dev-домен/`
- URL установки: `https://ваш-внешний-dev-домен/install`

## Production-сборка

Frontend в режиме `generate` bake-ит URL приложения на этапе сборки. Поэтому production host обязан быть известен заранее.

Пример build:

```bash
docker build \
  --build-arg VIRTUAL_HOST=https://app.example.com \
  --build-arg NUXT_PUBLIC_API_URL=https://app.example.com \
  -t bitrix24-timesheet:prod .
```

Минимальный runtime env для production:

- `VIRTUAL_HOST`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `JWT_SECRET`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `BUILD_TARGET=production`

Подробный rollout:

- [DEPLOY_README.md](./DEPLOY_README.md)
- [docs/PRODUCTION_ROLLOUT_GUIDE.md](./docs/PRODUCTION_ROLLOUT_GUIDE.md)

## Основные документы

- [docs/INSTALLATION_GUIDE.md](./docs/INSTALLATION_GUIDE.md) — первичная установка и настройка
- [docs/TECHNICAL_DOCUMENTATION.md](./docs/TECHNICAL_DOCUMENTATION.md) — архитектура и ключевые модули
- [docs/LOCAL_DEV_TROUBLESHOOTING.md](./docs/LOCAL_DEV_TROUBLESHOOTING.md) — только локальная диагностика dev-контура
- [Application_Documentation.md](./Application_Documentation.md) — продуктовое описание

## Важные замечания

- production и local-dev теперь считаются разными контурами;
- production URL должен совпадать:
  - в Bitrix24 settings;
  - в build arg `VIRTUAL_HOST`;
  - в runtime env `VIRTUAL_HOST`;
- после смены production-домена требуется переустановка или повторный bind placement’ов в Bitrix24;
- локальный `.env` не коммитится.
