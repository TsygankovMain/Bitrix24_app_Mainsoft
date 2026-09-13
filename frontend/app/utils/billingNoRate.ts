/**
 * Что стоит предупреждение no_rate в деньгах.
 *
 * Сервер сообщает только количество записей без ставки. Само по себе это
 * ничего не значит для человека: «у 12 записей нет ставки» звучит как мелкая
 * придирка, а на деле означает, что часть работы уйдёт клиенту бесплатно —
 * строка встанет в счёт с нулевой ценой и нулевой суммой.
 *
 * Поэтому считаем две вещи, которых в ответе нет:
 *
 *  1. ЧАСЫ по строкам с нулевой ценой — это факт, он берётся из предпросмотра;
 *  2. ОЦЕНКУ потери — те же часы по средней цене остальных строк отбора.
 *
 * Оценка честно называется оценкой: настоящей ставки у этих часов нет нигде
 * (ни в снимке списания, ни в карточке проекта, контракт, правило 5), и взять
 * её неоткуда. Средняя цена по тому же отбору — ближайшее осмысленное
 * приближение; когда цены нет ни у одной строки, оценка равна нулю и экран
 * говорит, что считать не по чему, а не показывает «потеряется 0 ₽».
 *
 * Исключённые строки в расчёт не идут: человек уже решил их судьбу, и
 * пугать его суммой по строке, которой в счёте не будет, незачем.
 */

import { round2 } from './billingPreview'
import type { BillingLineDraft } from './billingPreview'
import type { BillingWarningPayload } from '~/types/billing'

export type BillingNoRateLine = {
  key: string
  projectId: string
  title: string
  hours: number
}

export type BillingNoRateSummary = {
  /** Есть ли вообще о чём говорить. */
  present: boolean
  /** Записей без ставки — число сервера, а не наше. */
  entriesCount: number
  /** Строки предпросмотра с нулевой ценой (не исключённые). */
  lines: BillingNoRateLine[]
  /** Часы, которые уйдут в счёт бесплатно. */
  zeroHours: number
  /** Средняя цена часа по строкам, у которых цена есть. */
  averageRate: number
  /** Оценка потери: zeroHours x averageRate. 0 — оценить не по чему. */
  estimatedLoss: number
  /** Названия проектов без ставки — по ним заполняют карточку проекта. */
  projectTitles: string[]
}

function warningCount(warning: BillingWarningPayload | null | undefined): number {
  const raw = warning?.count
  const value = typeof raw === 'number' ? raw : Number(raw)

  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0
}

/**
 * Сводка по строкам без цены.
 *
 * Предупреждение необязательно: строка с нулевой ценой может появиться и от
 * руки — человек стёр цену в предпросмотре. Такая строка тоже уйдёт бесплатно,
 * и молчать о ней нельзя, поэтому сводка считается по строкам, а предупреждение
 * даёт только количество записей за ними.
 */
export function summarizeBillingNoRate(
  drafts: BillingLineDraft[] | null | undefined,
  warning?: BillingWarningPayload | null
): BillingNoRateSummary {
  const list = Array.isArray(drafts) ? drafts : []
  const lines: BillingNoRateLine[] = []
  const projectTitles: string[] = []

  let zeroHours = 0
  let paidHours = 0
  let paidAmount = 0

  for (const draft of list) {
    if (!draft || draft.excluded) {
      continue
    }

    if (draft.rate > 0) {
      paidHours = round2(paidHours + draft.hours)
      paidAmount = round2(paidAmount + draft.amount)
      continue
    }

    zeroHours = round2(zeroHours + draft.hours)
    lines.push({
      key: draft.key,
      projectId: draft.projectId,
      title: draft.title,
      hours: draft.hours,
    })

    if (draft.title && !projectTitles.includes(draft.title)) {
      projectTitles.push(draft.title)
    }
  }

  const averageRate = paidHours > 0 ? round2(paidAmount / paidHours) : 0
  const entriesCount = warningCount(warning)

  return {
    present: lines.length > 0 || entriesCount > 0,
    entriesCount,
    lines,
    zeroHours,
    averageRate,
    estimatedLoss: averageRate > 0 ? round2(zeroHours * averageRate) : 0,
    projectTitles,
  }
}

/** Ключи строк без цены — чтобы исключить их одним нажатием. */
export function noRateLineKeys(summary: BillingNoRateSummary): string[] {
  return summary.lines.map(line => line.key)
}
