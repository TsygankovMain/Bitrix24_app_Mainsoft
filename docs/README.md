# Документация «Учёт трудозатрат»

Единый индекс документации проекта. Начните отсюда.

## 📘 Для пользователей и внедрения
| Документ | О чём |
|---|---|
| [../Application_Documentation.md](../Application_Documentation.md) | Что делает приложение, роли, сценарии |
| [RELEASES.md](./RELEASES.md) | Релизы — что нового для пользователей (человеческим языком) |
| [INSTALLATION_GUIDE.md](./INSTALLATION_GUIDE.md) | Установка приложения |
| [MARKETPLACE_DESCRIPTION.md](./MARKETPLACE_DESCRIPTION.md) | Описание для маркетплейса |
| [PRODUCTION_ROLLOUT_GUIDE.md](./PRODUCTION_ROLLOUT_GUIDE.md) | Раскатка в production |

## 🏗 Для команды и разработки
| Документ | О чём |
|---|---|
| [architecture/overview.md](./architecture/overview.md) | Обзор архитектуры (слои, потоки данных) |
| [architecture/feature-map.md](./architecture/feature-map.md) | Карта «фича → файлы кода» |
| [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) | Техническая документация |
| [CHANGELOG.md](./CHANGELOG.md) | Технический лог изменений |
| [BACKLOG.md](./BACKLOG.md) | Идеи и задачи на будущее |
| [LOCAL_DEV_TROUBLESHOOTING.md](./LOCAL_DEV_TROUBLESHOOTING.md) | Локальная разработка, типовые проблемы |
| [../DEPLOY_README.md](../DEPLOY_README.md) | Деплой |
| [../CLAUDE.md](../CLAUDE.md) | Навигация по проекту, команды, скиллы |

## 🧪 Спеки и архив
| Раздел | О чём |
|---|---|
| `superpowers/specs/` | Активные/будущие дизайн-спеки фич (brainstorming → план); создаются при проработке новой фичи |
| [archive/](./archive/) | Архив завершённого: исторические решения/аналитика (code-review, deploy-decision, perf-baseline, оценка UI Kit), выполненные планы спринтов, реализованные спеки |

## 🗂 Внутреннее
| Папка | О чём |
|---|---|
| [internal/](./internal/) | Платный функционал, billing |
| [internal/mockups/](./internal/mockups/) | HTML-мокапы интерфейсов (открываются в браузере) |

## Конвенции документирования
- **Любое изменение кода** → запись в [CHANGELOG.md](./CHANGELOG.md) (технически).
- **Пользовательское изменение** → запись в [RELEASES.md](./RELEASES.md) (человеческим языком).
- **Новая фича** → отражается в [architecture/feature-map.md](./architecture/feature-map.md).
- **Перед реализацией фичи** — дизайн-мокап в `internal/mockups/<область>/*.html` и (для крупных) спек в `superpowers/specs/`.
