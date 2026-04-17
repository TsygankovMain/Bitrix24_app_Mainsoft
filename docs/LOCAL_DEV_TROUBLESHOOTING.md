# Локальная диагностика dev-контура (Bitrix24 + CloudPub)

Короткий runbook для случаев, когда локальная версия приложения перестает открываться после перезапуска.

## 1. Базовая проверка окружения

1. Проверьте, что в `.env` заполнены:
- `CLIENT_ID`
- `CLIENT_SECRET`
- `VIRTUAL_HOST`
- `JWT_SECRET`
- `CLOUDPUB_TOKEN`
2. Перезапустите окружение:
- `make down`
- `make dev-python`
3. Проверьте логи:
- `make logs`

## 2. Ошибка `Blocked request. This host is not allowed`

Причина: Vite не разрешает внешний домен.

Что делать:
1. Добавьте cloudpub-домен в `frontend/nuxt.config.ts` в `vite.server.allowedHosts`.
2. Перезапустите окружение (`make down`, `make dev-python`).
3. Сделайте hard reload в браузере.

## 3. Ошибка `404` на `/_nuxt/Users/.../entry.async.js`

Причина: при туннеле часть запросов приходит без `@fs`.

Что делать:
1. Убедитесь, что в локальной версии есть rewrite `/_nuxt/Users/...` -> `/_nuxt/@fs/Users/...`:
- `frontend/nuxt.config.ts`
- `frontend/server/middleware/nuxt-fs-rewrite.ts`
2. Перезапустите окружение.
3. Откройте страницу в режиме hard reload.

## 4. Ошибка `500` на `/api/getToken`

Проверьте:
1. Контейнер `api` поднят и доступен.
2. `CLIENT_ID/CLIENT_SECRET` соответствуют текущему локальному приложению Bitrix24.
3. В Bitrix24 для локального приложения корректны:
- URL приложения (`https://<домен>/`)
- URL установки (`https://<домен>/install`)

## 5. Какие данные запрашивать у пользователя для диагностики

1. Скриншот вкладки Network по запросу `/embedded` или `/api/getToken`.
2. Статус-код, URL и ответ `Preview/Response`.
3. Скриншот вкладки Console.
4. Если есть проблемы с сетью (гостиница, публичный Wi-Fi):
- включить VPN и повторить запуск;
- повторить запуск через мобильный интернет;
- отправить скриншот результатов.
