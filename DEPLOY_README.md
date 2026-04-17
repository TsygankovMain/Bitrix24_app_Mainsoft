# Production Deploy Runbook

Этот документ описывает целевой production rollout приложения без CloudPub.

## 1. Каноническая схема

Используется один контейнер из корневого [Dockerfile](./Dockerfile):

- Nuxt собирается статически;
- сборка фронта копируется в backend image;
- Django отдает API и SPA с одного домена;
- Bitrix24 открывает приложение только по этому production-домену.

CloudPub и tunnel в production не используются.

## 2. Что должно быть готово до релиза

- production domain с валидным SSL;
- production database PostgreSQL;
- `CLIENT_ID` и `CLIENT_SECRET` Bitrix24-приложения;
- production URL приложения в Bitrix24;
- понимание, кто выполняет migrations как release step.

## 3. Build

Frontend bake-ит домен на этапе сборки. Поэтому `VIRTUAL_HOST` обязателен.

```bash
docker build \
  --build-arg VIRTUAL_HOST=https://app.example.com \
  --build-arg NUXT_PUBLIC_API_URL=https://app.example.com \
  -t bitrix24-timesheet:prod .
```

Если API работает на том же домене, `NUXT_PUBLIC_API_URL` можно оставить равным `VIRTUAL_HOST`.

## 4. Runtime env

Обязательные runtime переменные:

```env
BUILD_TARGET=production
VIRTUAL_HOST=https://app.example.com
CLIENT_ID=...
CLIENT_SECRET=...
JWT_SECRET=...
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=...
DB_PORT=5432
```

Опционально:

```env
DJANGO_ALLOWED_HOSTS=app.example.com
CORS_ALLOWED_ORIGINS=
SUPPORT_OPENLINE_CODE=...
```

## 5. Release step перед стартом

Текущий `start.sh` не запускает миграции автоматически. Значит release step обязателен:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Если нужен доступ в admin:

```bash
python manage.py createsuperuser
```

## 6. Настройки приложения в Bitrix24

В Bitrix24 должны быть указаны:

- URL приложения: `https://app.example.com/`
- URL установки: `https://app.example.com/install`

Важно:

- если раньше приложение было установлено через CloudPub или другой домен, после релиза нужен reinstall или повторный bind placement’ов;
- иначе Bitrix24 продолжит дергать старые handler URL.

## 7. Что теперь bind-ится

Backend install flow централизованно bind-ит:

- `TASK_VIEW_TAB`
- `SONET_GROUP_DETAIL_TAB`

Handler у обоих placement’ов должен вести на production root приложения.

## 8. Smoke test после деплоя

### Базовая доступность

Проверить:

- `/healthz`
- `/api/health`
- `/`

### Frontend ассеты

В `Network` проверить:

- `/_nuxt/*.js`
- `/_nuxt/*.css`

Они должны возвращать `200` и корректный MIME type, а не HTML fallback.

### Авторизация и init

Проверить:

- `/api/getToken`
- загрузку главной страницы;
- загрузку `/api/homepage/portfolio`;
- загрузку `/api/project-board/meta`.

### Bitrix placements

Проверить внутри Bitrix24:

- вкладку приложения в задаче (`TASK_VIEW_TAB`);
- открытие из карточки проекта/группы (`SONET_GROUP_DETAIL_TAB`);
- открытие отчетов и настроек.

## 9. Быстрый rollback

Если production release не проходит smoke test:

1. вернуть предыдущий рабочий image;
2. не менять Bitrix24 URL, если новый домен не подтвержден;
3. если URL уже был переключен, временно вернуть старый handler;
4. отдельно проверить:
   - build arg `VIRTUAL_HOST`;
   - runtime `VIRTUAL_HOST`;
   - наличие `frontend_build/index.html` в image;
   - доступность `/_nuxt/*`.

## 10. Связанные документы

- [README.md](./README.md)
- [docs/PRODUCTION_ROLLOUT_GUIDE.md](./docs/PRODUCTION_ROLLOUT_GUIDE.md)
- [docs/INSTALLATION_GUIDE.md](./docs/INSTALLATION_GUIDE.md)
- [docs/TECHNICAL_DOCUMENTATION.md](./docs/TECHNICAL_DOCUMENTATION.md)
