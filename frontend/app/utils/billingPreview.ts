/**
 * Предпросмотр документа: строки, правки, итоги.
 *
 * Экран предпросмотра позволяет исключить строку и поправить её текст и цену
 * (задача, пункт 2). Итоги после каждой такой правки считаются ЗДЕСЬ, а не в
 * шаблоне: сумма счёта — то самое число, из-за которого потом спорят с
 * клиентом, и считать его в выражении внутри v-for, которое ревью не может
 * прогнать (node:test через tsx не резолвит .vue), нельзя.
 *
 * Пересчёт намеренно НЕ доверяется серверу повторным preview: человек уже
 * увидел цифры, и второй круг к Битриксу ради вычитания одной строки менял бы
 * их у него под руками (часы могли измениться между запросами).
 */

import type { BillingLinePayload } from '~/types/billing'

/** Копейки. Всё, что считаем сами, округляем до них — и ровно один раз. */
export function round2(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }

  return Math.round((value + Number.EPSILON) * 100) / 100
}

function toNumber(value: unknown): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0
  }

  if (typeof value === 'string') {
    const normalized = value.trim().replace(/\s/g, '').replace(',', '.')
    const parsed = Number(normalized)
    return Number.isFinite(parsed) ? parsed : 0
  }

  return 0
}

/** Строка предпросмотра в состоянии интерфейса: с правками и признаком исключения. */
export type BillingLineDraft = {
  /** Ключ для v-for. Индекс исходного массива — строки не переупорядочиваются. */
  key: string
  projectId: string
  title: string
  hours: number
  rate: number
  amount: number
  /** Строка исключена из документа. */
  excluded: boolean
  /** Текст изменён человеком. */
  titleEdited: boolean
  /** Цена изменена человеком. */
  rateEdited: boolean
  /** Исходные значения — чтобы показать «было» и вернуть правку. */
  originalTitle: string
  originalRate: number
  originalAmount: number
}

/**
 * Ответ preview -> строки интерфейса.
 *
 * Сумму берём от сервера, а не считаем сами: в ней может быть заложена
 * логика, которой фронт не знает (контракт: ставка включает НДС,
 * vat_mode = included). Своя арифметика включается только когда человек
 * поправил цену — тогда старая сумма заведомо неверна.
 *
 * Строка без названия получает подстановку: пустая строка в счёте выглядит
 * как потерянные данные, а «Работы по проекту» честно описывает, что это.
 */
export function createBillingLineDrafts(lines: BillingLinePayload[] | null | undefined): BillingLineDraft[] {
  if (!Array.isArray(lines)) {
    return []
  }

  return lines.map((line, index) => {
    const hours = round2(toNumber(line?.hours))
    const rate = round2(toNumber(line?.rate))
    const serverAmount = round2(toNumber(line?.amount))
    const amount = serverAmount || round2(hours * rate)
    const title = String(line?.title || line?.project_name || '').trim() || 'Работы по проекту'

    return {
      key: `line-${index}`,
      projectId: String(line?.project_id ?? '').trim(),
      title,
      hours,
      rate,
      amount,
      excluded: false,
      titleEdited: false,
      rateEdited: false,
      originalTitle: title,
      originalRate: rate,
      originalAmount: amount,
    }
  })
}

/** Новый текст строки. Пустой текст не принимаем — возвращаем исходный. */
export function applyDraftTitle(draft: BillingLineDraft, title: string): BillingLineDraft {
  const next = String(title || '').trim()
  const value = next || draft.originalTitle

  return {
    ...draft,
    title: value,
    titleEdited: value !== draft.originalTitle,
  }
}

/**
 * Новая цена строки: сумма пересчитывается сразу.
 *
 * Отрицательную цену не принимаем — в первой версии нет ни сторно, ни
 * корректировочных документов (контракт, «Что не входит»), поэтому минус
 * здесь — это опечатка, а не сценарий.
 */
export function applyDraftRate(draft: BillingLineDraft, rate: unknown): BillingLineDraft {
  const value = Math.max(0, round2(toNumber(rate)))

  return {
    ...draft,
    rate: value,
    amount: round2(draft.hours * value),
    rateEdited: value !== draft.originalRate,
  }
}

/** Исключить строку или вернуть её обратно. */
export function toggleDraftExcluded(draft: BillingLineDraft, excluded?: boolean): BillingLineDraft {
  return {
    ...draft,
    excluded: typeof excluded === 'boolean' ? excluded : !draft.excluded,
  }
}

export type BillingTotals = {
  /** Сколько строк уйдёт в документ. */
  linesCount: number
  /** Сколько строк исключено. */
  excludedCount: number
  totalHours: number
  totalAmount: number
  /** Хотя бы одна строка осталась и её сумма больше нуля. */
  issuable: boolean
}

/**
 * Итоги по включённым строкам.
 *
 * Суммируем уже округлённые суммы строк, а не пересчитываем от часов и цены:
 * в печатной форме человек увидит именно строки, и итог обязан быть их
 * суммой, иначе счёт не сойдётся сам с собой на копейку.
 */
export function recalcBillingTotals(drafts: BillingLineDraft[]): BillingTotals {
  let totalHours = 0
  let totalAmount = 0
  let linesCount = 0
  let excludedCount = 0

  for (const draft of drafts) {
    if (draft.excluded) {
      excludedCount += 1
      continue
    }

    linesCount += 1
    totalHours = round2(totalHours + draft.hours)
    totalAmount = round2(totalAmount + draft.amount)
  }

  return {
    linesCount,
    excludedCount,
    totalHours,
    totalAmount,
    issuable: linesCount > 0 && totalAmount > 0,
  }
}

/**
 * Строки для POST /api/billing/documents.
 *
 * Контракт описывает тело этой ручки как фильтр, но исключённые строки и
 * поправленные цены иначе до сервера не доедут — отправляем их отдельным
 * полем lines[] тем же форматом, в котором preview их отдал (project_id,
 * title, hours, rate, amount). Сервер вправе пересчитать отбор заново: часы
 * он всё равно берёт по фильтру, а lines[] — это то, что человек утвердил
 * глазами.
 */
export function buildBillingLinesPayload(drafts: BillingLineDraft[]): BillingLinePayload[] {
  return drafts
    .filter(draft => !draft.excluded)
    .map((draft, index) => ({
      project_id: draft.projectId || null,
      title: draft.title,
      hours: draft.hours,
      rate: draft.rate,
      amount: draft.amount,
      sort: (index + 1) * 10,
    }))
}

/** Были ли правки — показываем пометку «строки изменены вручную». */
export function hasDraftEdits(drafts: BillingLineDraft[]): boolean {
  return drafts.some(draft => draft.excluded || draft.titleEdited || draft.rateEdited)
}
