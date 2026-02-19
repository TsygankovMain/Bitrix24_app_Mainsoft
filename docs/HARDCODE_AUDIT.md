# Аудит хардкода: подготовка к маркетплейсу

> **Дата**: 16.02.2026  
> **Статус**: ⚠️ Требуется рефакторинг перед публикацией

---

## Критичность

| Уровень | Описание |
|---------|----------|
| 🔴 **Критично** | Блокирует работу на другом портале |
| 🟡 **Средне** | Работает, но ограничивает гибкость |
| 🟢 **Допустимо** | Можно оставить как есть |

---

## Найденные проблемы

### 🔴 1. `embedded.vue` — полный набор захардкоженных кодов полей

**Файл:** `frontend/app/pages/embedded.vue`, строки 104–126

```javascript
// Строка 105
DEFAULT_SMART_PROCESS_ID: 1164,

// Строки 107–117 — конфигурация полей
FIELDS: {
    TASK_ID: 'ufCrm87_1761919581',
    EMPLOYEE: 'ufCrm87_1761919601',
    HOURS: 'ufCrm87_1761919617',
    IS_CONSIDERED: 'ufCrm87_1763717129',
    DESCRIPTION: 'ufCrm87_1762026149771',
    TASK_HIERARCHY: 'ufCrm87_1764191110',
    TITLE_HIERARCHY: 'ufCrm87_1764191133',
    PROJECT_ID: 'ufCrm87_1764265626',
    PROJECT_TITLE: 'ufCrm87_1764265641',
    DATE: 'ufCrm87_1764446274',
    TASK_NAME: 'ufCrm87_1764361585'
}

// Строки 120–121 — коды полей задачи
TASK_FIELDS: {
    OUR_INN: 'UF_TASKS_TASK_1758105743485',
    CLIENT_INN: 'UF_TASKS_TASK_1758026758173'
}

// Строки 124–125 — коды полей SPA
SPA_FIELDS: {
    OUR_INN: 'ufCrm87_1769624604091',
    CLIENT_INN: 'ufCrm87_1769624613999'
}
```

**Проблема:** Все коды полей (prefix `ufCrm87_`) генерируются Битрикс24 уникально для каждого портала. На другом портале эти коды будут иными, и виджет не будет работать.

**Решение:**
1. Загружать конфигурацию полей из `app.option` (через `useBitrixAuth` или прямым вызовом `app.option.get`) при инициализации `embedded.vue`
2. Инфраструктура маппинга уже существует: `settings/mapping.client.vue` + `ConfigurationService` на бэкенде. Нужно подключить `embedded.vue` к этой системе.

---

### 🔴 2. `project-report.client.vue` — дублирование захардкоженных полей

**Файл:** `frontend/app/pages/reports/project-report.client.vue`, строки 5–23

```javascript
const HOURS_FIELD_CODE = 'ufCrm87_1761919617'
const IS_CONSIDERED_FIELD_CODE = 'ufCrm87_1763717129'
const PROJECT_ID_FIELD_CODE = 'ufCrm87_1764265626'
const PROJECT_NAME_FIELD_CODE = 'ufCrm87_1764265641'
const TASK_NAME_FIELD_CODE = 'ufCrm87_1764361585'
const REFLECTION_DATE_FIELD_CODE = 'ufCrm87_1764446274'
const EMPLOYEE_FIELD_CODE = 'ufCrm87_1761919601'
const DESCRIPTION_FIELD_CODE = 'ufCrm87_1762026149771'
const TASK_HIERARCHY_ID_FIELD_CODE = 'ufCrm87_1764191110'
const TASK_HIERARCHY_TITLE_FIELD_CODE = 'ufCrm87_1764191133'

// Строка 23
const smartProcessId = ref<number>(1164)
```

**Проблема:** Тот же набор хардкоженных кодов, что и в `embedded.vue`. Этот отчёт работает напрямую с B24 API (без бэкенда), поэтому тоже не использует динамический маппинг.

**Решение:** Загружать конфигурацию из `app.option` при монтировании компонента.

---

### 🟡 3. `embedded.vue` и `task.vue` — ставка за час

**Файлы:**
- `frontend/app/pages/embedded.vue`, строка 19: `const clientHourRate = ref(3000)`
- `frontend/app/pages/task.vue`, строка 23: `const clientHourRate = ref(3000)`

**Проблема:** Фиксированная ставка 3000 руб/час. У разных клиентов ставки различаются.

**Решение:** Перенести в настройки конфигурации (`app.option`) или сделать редактируемым полем в UI настроек.

---

### 🟡 4. `embedded.vue` — коды полей задач (ИНН)

**Файл:** `frontend/app/pages/embedded.vue`, строки 120–125

Коды `UF_TASKS_TASK_1758105743485` и `UF_TASKS_TASK_1758026758173` — пользовательские поля задач (НАШ ИНН / ИНН клиента). Эти поля специфичны для конкретного портала.

**Решение:** Добавить эти поля в маппинг или убрать из обязательной функциональности (сделать опциональными).

---

### 🟢 5. Бэкенд — чист

Бэкенд (`services.py`, `views.py`, `configuration_service.py`) **не содержит хардкода**. Все коды полей загружаются динамически из `ConfigurationService.get_configuration_sync()`. ✅

---

### 🟢 6. Отчёты через бэкенд — чисты

Отчёты `employee.client.vue`, `project.client.vue`, `daily.client.vue`, `project-task.client.vue` используют бэкенд API для получения данных и не содержат хардкоженных кодов полей. ✅

---

## Сводная таблица

| Файл | Тип хардкода | Критичность | Кол-во |
|------|-------------|:-----------:|:------:|
| `embedded.vue` | Field codes | 🔴 | 15 |
| `embedded.vue` | entityTypeId | 🔴 | 1 |
| `embedded.vue` | UF_TASKS_TASK_ | 🟡 | 2 |
| `embedded.vue` | clientHourRate | 🟡 | 1 |
| `project-report.client.vue` | Field codes | 🔴 | 10 |
| `project-report.client.vue` | entityTypeId | 🔴 | 1 |
| `task.vue` | clientHourRate | 🟡 | 1 |

**Итого:** 31 хардкоженное значение, из которых 27 критичных (🔴).

---

## Рекомендуемый план исправления

### Фаза 1 (Блокер для маркетплейса)
1. Создать composable `useAppConfig()` для загрузки конфигурации из `app.option`
2. Подключить `embedded.vue` к динамической конфигурации
3. Подключить `project-report.client.vue` к динамической конфигурации
4. Добавить fallback на дефолтные значения при отсутствии конфигурации

### Фаза 2 (Улучшения)
5. Вынести `clientHourRate` в настройки
6. Сделать поля задач (ИНН) опциональными с UI-настройкой
7. Добавить валидацию конфигурации при запуске

### Приблизительная оценка
- Фаза 1: ~4–6 часов
- Фаза 2: ~2–3 часа
