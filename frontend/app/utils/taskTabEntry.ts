/**
 * Черновик записи в форме списания вкладки задачи.
 *
 * Форма раскрывается прямо в списке (инлайн), поэтому её состояние живёт
 * рядом со строкой, а не в одном модальном окне на весь экран. Правка и
 * создание — один и тот же черновик, отличаются только наличием `id`: так же,
 * как это было в прежней форме, и так же, как ждёт `prepareEntryFields`.
 *
 * Чистые решения собраны здесь: что подставить в новую запись, во что
 * превращается существующая запись дерева и когда разделение записи
 * недопустимо. Проверки разделения особенно важны: ошибка в них молча
 * создаёт вторую запись и портит итоги по задаче.
 */

import type { TaskWorkspaceItem } from '~/types/task-workspace'
import { formatHoursNumber } from './taskTabFormat'
import { makeNewEntryDraft, type EntryDraft } from './timesheetEntry'

/**
 * `splitInvert` — «у отделённой части перевернуть признак учёта». Нужен,
 * когда часть часов решили не учитывать: отделяем их и снимаем флаг одним
 * действием, не создавая запись руками.
 */
export interface TaskEntryDraft extends EntryDraft {
  splitInvert: boolean
}

/**
 * Куда раскрыта форма.
 *
 * `create` — под шапкой задачи, `edit` — под самой записью. Якорь один на всё
 * дерево: двух форм одновременно не бывает, иначе человек правит одну, а
 * сохраняет другую.
 */
export interface TaskFormAnchor {
  kind: 'create' | 'edit'
  taskId: string
  itemId?: string
}

/**
 * Черновик новой записи на конкретную задачу дерева.
 *
 * Дата пересчитывается по локальному календарю поверх `makeNewEntryDraft`:
 * тот берёт её из `toISOString()`, то есть по UTC, и в Москве после 21:00
 * подставлял бы завтрашний день. Сам `makeNewEntryDraft` не трогаем — он
 * покрыт своими тестами и остаётся источником остальных значений по умолчанию.
 */
export function makeTaskEntryDraft(options: {
  taskId: string
  employeeId?: string | number | null
  today: Date
}): TaskEntryDraft {
  return {
    ...makeNewEntryDraft(options),
    date: toDateInputValue(options.today),
    splitInvert: false
  }
}

/**
 * Черновик правки существующей записи.
 *
 * Часы приходят из Битрикса и строкой, и числом — приводим к числу здесь,
 * иначе `input[type=number]` получает строку и арифметика разделения даёт
 * склейку («2» + «0.5» = «20.5»).
 */
export function draftFromItem(item: TaskWorkspaceItem, taskId: string): TaskEntryDraft {
  const hours = Number(item.hours)

  return {
    id: item.id,
    taskId,
    description: item.description || '',
    employeeId: item.employeeId,
    date: normalizeDraftDate(item.date || item.createdTime),
    hours: Number.isFinite(hours) ? hours : 0,
    isConsidered: Boolean(item.isConsidered),
    splitHours: 0,
    keepOriginalConsidered: false,
    splitInvert: false
  }
}

/** `input[type=date]` понимает только YYYY-MM-DD — время и зону отрезаем. */
export function normalizeDraftDate(value?: string | null): string {
  const raw = String(value || '').trim()
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})/)
  if (match) {
    return match[1] as string
  }

  const parsed = raw ? new Date(raw) : null
  if (parsed && !Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().split('T')[0] as string
  }

  return ''
}

/** Текст ошибки или null. Пустое описание допустимо — часы важнее слов. */
export function validateEntryDraft(draft: Pick<TaskEntryDraft, 'hours' | 'employeeId' | 'date'>): string | null {
  const hours = Number(draft.hours)
  if (!Number.isFinite(hours) || hours <= 0) {
    return 'Укажите часы больше нуля.'
  }

  if (hours > 24) {
    return 'За один день нельзя списать больше 24 часов.'
  }

  if (!String(draft.employeeId || '').trim()) {
    return 'Выберите сотрудника.'
  }

  if (!normalizeDraftDate(draft.date)) {
    return 'Укажите дату списания.'
  }

  return null
}

/**
 * Проверка разделения записи.
 *
 * Отделить можно только часть: ноль и «всё целиком» не создают новую запись,
 * а портят исходную (в первом случае появляется пустышка, во втором у
 * оригинала остаётся ноль часов).
 */
export function validateSplit(draft: Pick<TaskEntryDraft, 'id' | 'hours' | 'splitHours'>): string | null {
  if (!draft.id) {
    return 'Разделить можно только сохранённую запись.'
  }

  const splitHours = Number(draft.splitHours)
  const hours = Number(draft.hours)

  if (!Number.isFinite(splitHours) || splitHours <= 0) {
    return 'Укажите, сколько часов отделить.'
  }

  if (!Number.isFinite(hours) || splitHours >= hours) {
    return 'Отделить можно только часть записи — меньше, чем в ней есть.'
  }

  return null
}

/**
 * Быстрые кнопки часов: типовые длительности вместо набора с клавиатуры.
 *
 * В макете нарисованы 0,5 / 1 / 2 / 4. Восьмёрка добавлена сверх макета: полный
 * рабочий день — самое частое списание на длинных задачах, а набирать его
 * руками при наличии ряда кнопок выглядит как недоработка. Кнопка ставит
 * значение целиком, а не прибавляет: прибавление («+0,5») на четырёх нажатиях
 * даёт 2 ч и не даёт способа быстро вернуться к 0,5.
 */
export const QUICK_HOURS = [0.5, 1, 2, 4, 8] as const

/** Те же значения с подписями по-русски: «0,5», а не «0.5». */
export function quickHourOptions(): Array<{ label: string, value: number }> {
  return QUICK_HOURS.map(value => ({ value, label: formatHoursNumber(value) }))
}

/**
 * Быстрые кнопки даты. `today` передаётся снаружи ради чистоты функции.
 *
 * Две кнопки, как в макете: «Сегодня» и «Вчера». Третьей («Позавчера») нет
 * намеренно — дальше двух дней люди вспоминают конкретное число, а не
 * «сколько-то дней назад», и для этого рядом стоит обычный выбор дня.
 */
export function quickDateOptions(today: Date): Array<{ label: string, value: string }> {
  const yesterday = new Date(today.getTime())
  yesterday.setDate(yesterday.getDate() - 1)

  return [
    { label: 'Сегодня', value: toDateInputValue(today) },
    { label: 'Вчера', value: toDateInputValue(yesterday) }
  ]
}

/**
 * Дата для `input[type=date]` по локальному календарю пользователя.
 *
 * Через `toISOString()` считать нельзя: в Москве вечером это уже следующий
 * день по UTC, и «Сегодня» подставляло бы завтра.
 */
export function toDateInputValue(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
