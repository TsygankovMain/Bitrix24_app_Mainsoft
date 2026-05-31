# Глобальный прогресс-оверлей для всех фоновых операций

## Контекст
Прогресс-оверлей с маскотом 🦫 (`components/common/ProgressOverlay.vue`) сейчас показывается только в ИНН-панели/модалке и на странице «Сырые данные» (синк/экспорт). При формировании отчётов («Сформировать») и других фоновых операциях пользователь видит лишь спиннер на кнопке и текст «Загрузка…» — непонятно, идёт процесс или зависло. Нужно показывать единый прогресс-оверлей **везде, где есть фоновая обработка**.

## Принятые решения
| Развилка | Решение |
|---|---|
| Охват | Все фоновые операции: формирование отчётов, выгрузки Excel, синхронизации, ИНН-простановка. |
| Архитектура | Единый **глобальный** оверлей (один на приложение), управляемый стором — не по странице. |
| Реализация | Sonnet-агенты. |

## Архитектура

### Стор `frontend/app/stores/progress.ts` (Pinia)
- Состояние: `count` (число активных операций), `title` (string), `done` (number), `total` (number).
- Геттер `active = count > 0`.
- Методы:
  - `begin(title: string, total = 0)` — `count++`, установить `title`/`done=0`/`total`.
  - `update(done: number, total?: number)` — обновить прогресс текущей операции.
  - `end()` — `count = max(0, count-1)`; при `count===0` сбросить `title/done/total`.
- Счётчик `count` защищает от преждевременного скрытия при параллельных операциях; `title`/`done`/`total` отражают последнюю начатую операцию.

### Единый оверлей в `frontend/app/app.vue`
- Смонтировать один `<ProgressOverlay :visible="progress.active" :title="progress.title" :done="progress.done" :total="progress.total" />` (через Teleport — позиция не важна). `ProgressOverlay` уже поддерживает неопределённый режим (нет `total` → Бобёр «бежит на месте») и режим с процентом (есть `total`).
- Если структура `app.vue` не позволяет (например, только `<NuxtLayout>`) — смонтировать в `layouts/default.vue` (основное приложение). Проверить при реализации.

### Подключение точек входа
- **`composables/useReportGenerator.ts`** — в `generateReport`: `progress.begin('Формирование отчёта…')` в начале, `progress.end()` в `finally`. Покрывает все 7 отчётов одним изменением. (Существующий `setLoading` оставить для inline-состояний страниц.)
- **Выгрузки Excel** — в каждом `handleExport`/`handleExportExcel` (7 страниц reports/*): обернуть `progress.begin('Формирование Excel…')` … `finally end()`.
- **Синхронизации** — `raw-data.client.vue::handleSync`, синхронизация доски проектов (`projects/index.client.vue`) и пр.: `begin('Синхронизация…')`/`end()`.
- **ИНН-простановка** — `InnBackfillPanel.vue` (массовая) и `InnAssignModal.vue`: перенести с локального `ProgressOverlay` на стор с `begin('Простановка ИНН…', total)` + `update(done)` по чанкам + `end()`.

### Удаление локальных оверлеев
Убрать локальные `<ProgressOverlay>` из `InnBackfillPanel.vue`, `InnAssignModal.vue`, `raw-data.client.vue` — заменить вызовами стора (единая точка правды). Импорт `ProgressOverlay` в этих файлах удалить.

## Файлы
- Create: `frontend/app/stores/progress.ts`.
- Modify: `frontend/app/app.vue` (или `layouts/default.vue`), `composables/useReportGenerator.ts`, `pages/reports/{employee,project,daily,project-task,revenue-leakage,time-discipline,focus-analysis}.client.vue`, `pages/reports/raw-data.client.vue`, `components/reports/InnBackfillPanel.vue`, `components/reports/InnAssignModal.vue`, `pages/projects/index.client.vue`.

## Риски
- Не «потерять» `end()` при ошибках → всегда в `finally`.
- Параллельные операции с разными `title` — показывается последняя; приемлемо (операции обычно последовательны).
- Оверлей блокирует ввод (затемнение) — это и нужно на время фоновой обработки; убедиться, что `end()` вызывается на всех путях (успех/ошибка/пустой результат).

## Верификация
1. На каждом отчёте «Сформировать» → виден Бобёр (неопределённый), исчезает по завершении/ошибке.
2. «Скачать Excel» на отчётах → Бобёр на время формирования.
3. Синхронизация (raw-data, доска) → Бобёр.
4. ИНН-простановка → Бобёр с процентом X/Y (как раньше), но через глобальный оверлей; локальных оверлеев не осталось.
5. `nuxt prepare` чист; нет битых импортов удалённого локального `ProgressOverlay`.
