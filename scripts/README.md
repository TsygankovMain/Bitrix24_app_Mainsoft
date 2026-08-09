# Scripts README

Эта папка относится к локальной разработке и вспомогательной автоматизации.

Важно:

- production rollout приложения не строится вокруг CloudPub;
- скрипты из этой папки не считаются production release pipeline;
- основная production-сборка описана в [DEPLOY_README.md](../DEPLOY_README.md).

## Что здесь есть

### `release-readiness-check.sh`

Локальная проверка technical gate перед UAT/релизом.

Что проверяет:

- `py_compile` для backend Python файлов;
- `tsc --noEmit` для frontend;
- наличие миграции `0011_timesheetitem_hourly_rate_snapshot.py`.

Запуск:

```bash
./scripts/release-readiness-check.sh
```

### `security-scan.sh`

Аудит уязвимостей в зависимостях. Запускается через `make security-scan`.

### `security-tests.sh`

Оркестрованный набор security-тестов. Запускается через `make security-tests`.

### `probe-backend.sh`

Диагностика backend-эндпоинтов: проверяет, отвечает ли API и с какими кодами.

### `test-cloudpub.sh`

Только dev-диагностика tunnel-сценария.

Использовать, если:

- нужно понять, выдаёт ли CloudPub внешний домен;
- нужно проверить, почему локальная версия не открывается внутри Bitrix24.

### `create-version.sh` / `delete-version.sh`

Клонирование текущего проекта в `versions/<name>` и удаление такой копии.
Вызываются через `make create-version VERSION=<name>` и `make delete-version VERSION=<name>`.

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
