/**
 * Раскладка вкладки задачи (`pages/embedded.vue`) по ширине фрейма.
 *
 * Вкладка живёт в iframe карточки задачи Битрикс24, и её ширину задаёт портал,
 * а не окно браузера: на широком мониторе это ~900 px, в правой колонке
 * карточки — 640 px, на телефоне — около 400 px. До редизайна вкладка была
 * жёсткой сеткой `1fr 380px` без брейкпоинтов: на 640 px дереву задач
 * оставалось ~230 px, на 400 px вёрстка ломалась.
 *
 * Здесь — одно решение «какая раскладка при такой ширине», вынесенное из
 * компонента: node:test через tsx не резолвит .vue, поэтому пороги и то, что
 * из них следует, проверяются только так. Компонент сам измеряет ширину
 * (`window.innerWidth` внутри фрейма) и раздаёт результат детям пропом.
 *
 * Колонка всегда одна — на любой ширине. Меняется не число колонок, а
 * плотность: где помещается мета записи, где итоги задачи идут отдельной
 * строкой, насколько глубоко отбивается вложенность.
 */

export type TaskTabLayoutMode = 'xwide' | 'wide' | 'medium' | 'narrow'

export interface TaskTabLayout {
  mode: TaskTabLayoutMode
  /** Сотрудник и дата записи — в одной строке с описанием (иначе строкой ниже). */
  inlineEntryMeta: boolean
  /** Итоги задачи — отдельной строкой под заголовком, а не справа от него. */
  stackedTaskTotals: boolean
  /** Поля фильтра — в колонку, каждое на всю ширину. */
  stackedFilters: boolean
  /** Подписи действий у записи («Изменить»/«Удалить») скрыты, остаются иконки. */
  iconOnlyEntryActions: boolean
  /** Отступ одного уровня вложенности, px. */
  indentStep: number
}

/**
 * Пороги измерены на живой вёрстке, а не подобраны на глаз.
 *
 * Строка записи, кроме описания, несёт точку-индикатор, мету (сотрудник и
 * дата — около 150 px), часы (~55 px) и два действия. Шапка задачи несёт
 * стрелку, кнопку «+» и итоги (три сегмента — около 340 px). Отсюда и границы:
 *
 *  - 900 px и шире: помещается всё. Итоги встают справа от названия задачи
 *    (названию остаётся ~440 px), у действий видны подписи;
 *  - 660–899 px: подписи действий и итоги справа уже не помещаются — при
 *    подписях описание сжималось до 114 px, а название задачи до 136 px.
 *    Итоги уходят строкой ниже, действия остаются иконками, мета записи ещё
 *    стоит в строке (описанию остаётся ~300 px);
 *  - 480–659 px: мета уходит под описание — иначе описанию остаётся ~125 px;
 *  - уже 480 px: в колонку складывается и фильтр.
 */
export const TASK_TAB_XWIDE_FROM = 900

/** Ниже этой ширины итоги задачи и подписи действий перестают помещаться. */
export const TASK_TAB_WIDE_FROM = 660

/** Ниже этой ширины мета записи перестаёт помещаться в строку с описанием. */
export const TASK_TAB_MEDIUM_FROM = 480

const LAYOUTS: Record<TaskTabLayoutMode, TaskTabLayout> = {
  xwide: {
    mode: 'xwide',
    inlineEntryMeta: true,
    stackedTaskTotals: false,
    stackedFilters: false,
    iconOnlyEntryActions: false,
    indentStep: 16
  },
  wide: {
    mode: 'wide',
    inlineEntryMeta: true,
    stackedTaskTotals: true,
    stackedFilters: false,
    iconOnlyEntryActions: true,
    indentStep: 16
  },
  medium: {
    mode: 'medium',
    inlineEntryMeta: false,
    stackedTaskTotals: true,
    stackedFilters: false,
    iconOnlyEntryActions: true,
    indentStep: 10
  },
  narrow: {
    mode: 'narrow',
    inlineEntryMeta: false,
    stackedTaskTotals: true,
    stackedFilters: true,
    iconOnlyEntryActions: true,
    indentStep: 6
  }
}

/**
 * Раскладка по ширине фрейма в px.
 *
 * Ширина 0 и любое неизмеримое значение — это момент до первого измерения
 * (setup отработал, onMounted ещё нет). Отдаём раскладку `wide`: она безопасна
 * в обе стороны — не рассыпается на узком фрейме и не выглядит пустой на
 * широком, а после измерения переключение происходит один раз.
 */
export function resolveTaskTabLayout(width: number): TaskTabLayout {
  if (!Number.isFinite(width) || width <= 0) {
    return LAYOUTS.wide
  }

  if (width >= TASK_TAB_XWIDE_FROM) {
    return LAYOUTS.xwide
  }

  if (width >= TASK_TAB_WIDE_FROM) {
    return LAYOUTS.wide
  }

  if (width >= TASK_TAB_MEDIUM_FROM) {
    return LAYOUTS.medium
  }

  return LAYOUTS.narrow
}

/**
 * Сколько видимых строк дерева считается «длинным деревом».
 *
 * Порог не про красоту, а про то, видно ли низ вкладки. Строка задачи — 52 px,
 * строка записи — 40 px; двенадцать строк это примерно 550 px содержимого,
 * то есть ровно тот момент, когда панель выгрузок в конце вкладки уезжает за
 * нижний край типового экрана карточки задачи (~700 px под содержимое минус
 * шапка карточки, вкладки и шапка самого приложения).
 */
export const TASK_TAB_LONG_TREE_ROWS = 12

/**
 * Нужно ли продублировать «В отчёт Битрикс24» и «Excel» в шапке вкладки.
 *
 * В макете эти кнопки закреплены у нижнего края. Во вкладке задачи так не
 * получится: высоту iframe приложение само подгоняет под содержимое
 * (`requestIframeAutoHeight` → `BX24.fitWindow`), своей полосы прокрутки у
 * фрейма нет, прокручивается страница портала. И `position: sticky`, и
 * `position: fixed` внутри такого фрейма считаются от его собственной области
 * просмотра, которая равна всему содержимому, — значит прилипнут к низу
 * содержимого, а не к низу экрана. Сколько портальная страница прокручена,
 * приложению никто не сообщает.
 *
 * Поэтому кнопки остаются обычным блоком в конце вкладки (он ничего не
 * перекрывает), а на длинном дереве те же два действия дополнительно
 * появляются в строке инструментов наверху — она видна сразу при открытии
 * вкладки. На коротком дереве дубля нет: там низ и так на экране.
 */
export function shouldMirrorFooterActions(visibleRows: number): boolean {
  if (!Number.isFinite(visibleRows)) {
    return false
  }

  return visibleRows >= TASK_TAB_LONG_TREE_ROWS
}

/** Класс-модификатор на корне вкладки — по нему цепляются медиа-независимые стили. */
export function taskTabLayoutClass(mode: TaskTabLayoutMode): string {
  return `task-tab--${mode}`
}

/**
 * Отступ подзадачи от левого края, px.
 *
 * Глубина ограничена: дерево задач Битрикс24 бывает и на семь уровней, а
 * прежний `margin-left: <level>rem` на каждом уровне съедал ширину до тех пор,
 * пока описание записи не переставало помещаться совсем.
 */
export function taskTabIndent(level: number, layout: TaskTabLayout, maxLevels = 3): number {
  if (!Number.isFinite(level) || level <= 0) {
    return 0
  }

  return Math.min(Math.floor(level), maxLevels) * layout.indentStep
}
