# Scripts README

Эта папка относится к локальной разработке и вспомогательной автоматизации.

Важно:

- production rollout приложения больше не строится вокруг CloudPub;
- scripts из этой папки не считаются production release pipeline;
- основная production-сборка описана в [DEPLOY_README.md](../DEPLOY_README.md).

## Что здесь может использоваться

### `dev-init.sh`

Локальная инициализация dev-контура.

Сценарий:

- подготовка `.env`;
- запуск локальных контейнеров;
- при необходимости работа с tunnel для Bitrix24 local dev.

### `test-cloudpub.sh`

Только dev-диагностика tunnel-сценария.

Использовать, если:

- нужно понять, выдает ли CloudPub внешний домен;
- нужно проверить, почему локальная версия не открывается внутри Bitrix24.

### `fix-php.sh`

Legacy-скрипт для старого PHP-контура. К production-модели текущего Django/Nuxt-приложения не относится.

## Что не нужно делать через scripts

Не использовать эти скрипты как production deploy pipeline.

Для production:

- использовать root `Dockerfile`;
- использовать production domain;
- настраивать Bitrix24 на production URL;
- выполнять migrations как release step.

См.:

- [README.md](../README.md)
- [DEPLOY_README.md](../DEPLOY_README.md)
- [docs/PRODUCTION_ROLLOUT_GUIDE.md](../docs/PRODUCTION_ROLLOUT_GUIDE.md)
