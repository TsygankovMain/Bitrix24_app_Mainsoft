# Local Dev Troubleshooting

Этот документ относится только к локальной разработке.

Если приложение уже развернуто в production, используйте:

- [DEPLOY_README.md](../DEPLOY_README.md)
- [PRODUCTION_ROLLOUT_GUIDE.md](./PRODUCTION_ROLLOUT_GUIDE.md)

## 1. Базовая проверка local-dev

Проверьте:

- `.env` создан из `.env.example`;
- заполнены `CLIENT_ID`, `CLIENT_SECRET`, `JWT_SECRET`, `VIRTUAL_HOST`, `DB_*`;
- если используется внешний tunnel, задан `CLOUDPUB_TOKEN`;
- поднято окружение `make dev-python`.

## 2. Ошибка `Blocked request. This host is not allowed`

Это dev-only ошибка Vite.

Что проверить:

1. внешний dev host добавлен в `NUXT_ALLOWED_HOSTS` или разрешен в `frontend/nuxt.config.ts`;
2. окружение перезапущено;
3. выполнен hard reload.

## 3. Ошибка `404` на `/_nuxt/Users/.../entry.async.js`

Это тоже dev-only история, связанная с Vite и `@fs`.

Что делать:

1. проверить, что включен rewrite `/_nuxt/Users/... -> /_nuxt/@fs/Users/...`;
2. убедиться, что используется актуальная локальная версия `frontend/nuxt.config.ts`;
3. перезапустить dev frontend.

## 4. Ошибка `500` на `/api/getToken`

Проверить:

- поднят ли backend;
- корректны ли `CLIENT_ID/CLIENT_SECRET`;
- совпадает ли локальный внешний URL приложения с Bitrix24 settings;
- не истекла ли авторизация приложения на портале.

## 5. Если локальная версия открывается нестабильно

Проверить по порядку:

1. `make down`
2. `make dev-python`
3. `make logs`
4. hard reload в браузере
5. открыть `Network` и проверить:
   - `/api/getToken`
   - `/_nuxt/*`
   - `/embedded`

## 6. Что важно помнить

- CloudPub нужен только для local dev;
- production-баги и local tunnel-баги теперь нужно различать отдельно;
- если проблема воспроизводится только через tunnel, это не повод менять production-контур.
