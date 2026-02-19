# Техническая документация TimeTracker Pro

## Оглавление
1. [Архитектура](#1-архитектура)
2. [Стек технологий](#2-стек-технологий)
3. [Структура проекта](#3-структура-проекта)
4. [Бэкенд (Python/Django)](#4-бэкенд)
5. [Фронтенд (Nuxt 3)](#5-фронтенд)
6. [Конфигурация и маппинг](#6-конфигурация-и-маппинг)
7. [Модель данных](#7-модель-данных)
8. [API эндпоинты](#8-api-эндпоинты)
9. [Деплой](#9-деплой)

---

## 1. Архитектура

```
┌─────────────────────┐      ┌─────────────────────────┐
│   Битрикс24 Cloud   │◀────▶│   Frontend (Nuxt 3)     │
│   (Смарт-процесс)   │      │   - Виджет (embedded)   │
│                     │      │   - Отчёты              │
│                     │      │   - Настройки           │
└─────────────────────┘      └────────┬────────────────┘
                                      │ REST API
                              ┌───────▼────────────────┐
                              │  Backend (Django)       │
                              │  - Синхронизация        │
                              │  - Агрегация отчётов    │
                              │  - Конфигурация         │
                              └───────┬────────────────┘
                                      │
                              ┌───────▼────────────────┐
                              │  PostgreSQL             │
                              │  (TimesheetItem,        │
                              │   Bitrix24Account)      │
                              └────────────────────────┘
```

**Два режима работы фронтенда:**
- **Standalone** (главная, отчёты, настройки) — работает через бэкенд Django
- **Embedded** (виджет задачи) — работает напрямую с Bitrix24 API через JSSDK (без бэкенда)

---

## 2. Стек технологий

| Слой | Технология |
|------|-----------|
| Frontend | Nuxt 3, Vue 3, TypeScript |
| UI Library | @bitrix24/b24ui-nuxt, Tailwind CSS |
| B24 SDK | @bitrix24/b24jssdk |
| Backend | Python 3.11+, Django 4.x |
| B24 SDK (Python) | b24pysdk |
| Database | PostgreSQL |
| Server | uvicorn (ASGI) |
| Container | Docker |
| Export | SheetJS (xlsx) |

---

## 3. Структура проекта

```
dev_pyton_app/
├── backends/python/api/main/
│   ├── configuration_service.py  — Конфигурация через app.option
│   ├── models.py                 — Django модели (TimesheetItem, Bitrix24Account)
│   ├── services.py               — BitrixDataService, ReportService
│   ├── views.py                  — API эндпоинты (отчёты, синхронизация)
│   └── urls.py                   — URL routing
├── frontend/app/
│   ├── pages/
│   │   ├── index.client.vue      — Дашборд (плитки отчётов)
│   │   ├── embedded.vue          — Виджет в задаче (TASK_VIEW_TAB)
│   │   ├── task.vue              — Полная страница задачи
│   │   ├── guide.client.vue      — Юзергайд
│   │   ├── install.client.vue    — Установщик
│   │   ├── reports/
│   │   │   ├── employee.client.vue       — Отчёт по сотрудникам
│   │   │   ├── project.client.vue        — Отчёт по проектам  
│   │   │   ├── project-task.client.vue   — Отчёт по проектам/задачам (НОВЫЙ)
│   │   │   ├── project-report.client.vue — Прямой отчёт (без бэкенда)
│   │   │   └── daily.client.vue          — Ежедневная нагрузка
│   │   └── settings/
│   │       ├── index.client.vue  — Главная настроек
│   │       └── mapping.client.vue — Маппинг полей
│   ├── components/
│   │   ├── TaskGroupComponent.vue — Группа задач в дереве
│   │   └── TaskItemRow.vue        — Строка метки времени
│   └── stores/
│       └── api.ts                — API store (запросы к бэкенду)
├── docs/                         — Документация
│   ├── MARKETPLACE_DESCRIPTION.md — Описание для Маркетплейса
│   ├── LOGO_PROMPT.md            — Промт для логотипа
│   └── ...
├── Dockerfile
├── docker-compose.yml
└── DEPLOY_README.md

---

## 4. Бэкенд

### Ключевые сервисы

**`ConfigurationService`** — управление конфигурацией:
- `get_configuration_sync()` — загрузка из `app.option` (JSON в поле `timestamp_config`)
- `save_configuration_sync()` — сохранение
- `get_smart_processes_sync()` — список доступных Смарт-процессов
- `get_sp_fields_sync()` — поля конкретного Смарт-процесса

**`BitrixDataService`** — загрузка данных:
- `fetch_all_items()` — пакетная загрузка всех меток из CRM (batches по 50, до 2500 за цикл)
- `fetch_users()` — загрузка пользователей

**`DataProcessingService`** — нормализация:
- `normalize_items()` — парсинг иерархий, вычисление проектов, валидация

**`ReportService`** — агрегация отчётов:
- `generate_employee_projects()` — Сотрудник → Проект → Задача
- `generate_project_employees()` — Проект → Сотрудник → Задача
- `generate_project_task_employees()` — Проект → Задача → Сотрудник
- `generate_daily_workload()` — Табель (матрица)

### Модели Django

**`Bitrix24Account`** — авторизация портала:
- `member_id`, `domain`, `auth_id`, `refresh_id`, `app_sid`

**`TimesheetItem`** — запись метки времени (кэш данных из Б24):
- `item_id_bitrix`, `task_id`, `employee_id`, `hours`
- `is_considered`, `description`, `date_reflection`
- `project_name`, `task_hierarchy_ids`, `task_hierarchy_titles`

---

## 5. Фронтенд

### Виджет (embedded.vue)

Встраивается в **блок задачи** (через placement `TASK_VIEW_TAB` или как Embedded Application).

**Особенности интеграции (SidePanel):**
- Приложение определяет контекст запуска (iframe в слайдере или iframe на странице).
- Использует **Native SidePanel API** (`BX24.openPath`) для открытия вспомогательных окон (Юзергайд, Настройки) внутри слайдера Битрикс24, сохраняя контекст задачи.
- Реализован **Fallback механизм** изменения размера окна (через `postMessage`) для корректного отображения модалок (Report Modal, Help Modal).

**Алгоритм работы:**
1. Получает `taskId` из placement options
2. BFS-обход подзадач (`tasks.task.list`)
3. Загрузка меток для всех задач (`crm.item.list`)
4. Построение дерева с кумулятивными итогами
5. CRUD операции напрямую через B24 API

**Ключевые функции:**
- `loadData()` — полная загрузка дерева задач + меток
- `saveCurrentItem()` — сохранение/создание метки (с иерархией)
- `splitItem()` — разделение записи с сохранением привязок
- `getTaskHierarchy()` — сбор полной иерархии задач до корня
- `findTaskIdForItem()` — поиск taskId по itemId в дереве

### UX/UI Особенности (Fast Adaptive Patch)
- **Адаптивность**: Полная поддержка мобильных устройств (flebox, wrapping).
- **Центрированные модалки**: Компоненты (`HelpSidePanel`, `ReportModal`) используют `Teleport` и центрирование для корректного отображения поверх iframe.
- **HTML-First Mockups**: Юзергайд использует не скриншоты, а верстку (Tailwind) для отображения интерфейса, что гарантирует актуальность и четкость.

### Отчёты

Отчёты `employee`, `project`, `project-task`, `daily` используют бэкенд API через `api.ts`:
- Загрузка данных: POST-запрос с фильтрами
- Синхронизация: вызов `/sync/` перед генерацией отчёта
- Экспорт: клиентская генерация XLSX через SheetJS

Отчёт `project-report` работает **напрямую** через B24 API (без бэкенда).

### Навигация

```
/                          — Дашборд
/reports/employee          — Отчёт по сотрудникам
/reports/project           — Отчёт по проектам
/reports/project-task      — Отчёт по проектам/задачам
/reports/daily             — Ежедневная нагрузка
/reports/project-report    — Прямой отчёт (без бэкенда)
/settings                  — Настройки
/settings/mapping          — Маппинг полей
/guide                     — Юзергайд
/embedded                  — Виджет задачи (TASK_VIEW_TAB)
/install                   — Установщик
```

---

## 6. Конфигурация и маппинг

### Бэкенд
Конфигурация хранится в `app.option` ключ `timestamp_config` (JSON):
```json
{
  "sp_entity_type_id": 1040,
  "fields_mapping": {
    "id_zadachi": "ufCrm10TaskId",
    "sotrudnik": "ufCrm10Employee",
    ...
  },
  "is_configured": true
}
```
Бэкенд загружает конфигурацию через `ConfigurationService.get_configuration_sync()` при каждом API-запросе.

### Фронтенд
- Используется `stores/fieldConfig.ts` (Pinia) для загрузки конфигурации при старте приложения.
- **Виджет (`embedded.vue`)** и все отчеты используют этот стор для получения ID полей.
- **Маппинг** и создание полей происходят на странице настроек (`settings/mapping.client.vue`) через прямой вызов Bitrix API (`userfieldconfig.add`).

---

## 7. Модель данных

### Основные поля (динамические ID)

Поля создаются автоматически с префиксом `UF_CRM_{id}_`. Маппинг хранит связь между внутренним ключом и реальным кодом поля в Битрикс24.

| Ключ | Назначение | Тип |
|------|------------|-----|
| `id_zadachi` | ID задачи | integer |
| `sotrudnik` | Сотрудник | employee |
| `kolichestvo_chasov` | Часы | double |
| `uchitivaem` | Учитываем? | boolean |
| `ne_uchitivaemie_chasi` | Не учтено | double |
| `opisanie` | Описание | string |
| `project_title` | Название проекта | string |
| `project_id` | ID проекта | integer |
| `data` | Дата | date |
| `task_name` | Название задачи | string |
| `our_inn` | Наш ИНН | string |
| `client_inn` | ИНН клиента | string |

### Иерархические поля

Поля `id_zadach_ierarhiya` / `title_zadach_ierarhiya` — **множественные** строковые поля, хранящие путь от корневой задачи:

```
Задача «Разработка» (ID: 901) → «Backend» (ID: 905)
id_zadach_ierarhiya:    ["901", "905"]
title_zadach_ierarhiya: ["Разработка", "Backend"]
```

---

## 8. API эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/sync/` | Синхронизация данных из Б24 |
| POST | `/api/report/...` | Генерация отчетов (employee, project, daily) |
| POST | `/api/smart-processes/create` | Создание Смарт-процесса (backend fallback) |
| POST | `/api/smart-processes/create-fields` | Создание полей (backend fallback) |
| POST | `/api/configuration/save` | Сохранение конфига (`app.option.set`) |
| GET | `/api/configuration` | Чтение конфига |

Все эндпоинты ожидают `AUTH_ID` в теле запроса для авторизации.

---

## 9. Деплой

Подробная инструкция: [DEPLOY_README.md](../DEPLOY_README.md)

**Кратко:**
1. Docker-образ собирается из корневого `Dockerfile`
2. Порт: 8000 (uvicorn)
3. Внешний PostgreSQL
4. Переменные окружения: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `SECRET_KEY`, `VIRTUAL_HOST`
5. После деплоя: `python manage.py migrate`
