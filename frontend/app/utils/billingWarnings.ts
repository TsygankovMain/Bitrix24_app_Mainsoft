/**
 * Предупреждения предпросмотра человеческим текстом.
 *
 * Коды заданы контрактом (ответ preview): period_open, already_invoiced,
 * no_rate, mixed_companies. Сервер присылает КОД, а не фразу, и это правильно:
 * фраза — дело интерфейса, и менять её не должно стоить релиза бэкенда.
 *
 * Блокирующее предупреждение ровно одно — mixed_companies («в отборе
 * несколько клиентов — выставлять нельзя», правило 4 контракта: один клиент
 * на документ, ошибка, а не молчаливое объединение). Остальные предупреждения
 * не мешают выставить, но должны быть прочитаны, поэтому блокеры и
 * предупреждения показываются РАЗДЕЛЬНО — тот же приём, что на экране
 * закрытия месяца: свалить их в один список значит научить людей нажимать
 * «Выставить» не читая.
 */

import { formatRecordsRu } from './billingFormat'
import type { BillingWarningPayload } from '~/types/billing'

export type BillingWarningView = {
  code: string
  title: string
  text: string
  /** Выставление запрещено, пока предупреждение не снято. */
  blocking: boolean
}

type WarningTemplate = {
  title: string
  /** Текст по количеству затронутых записей, если сервер его прислал. */
  text: (warning: BillingWarningPayload) => string
  blocking: boolean
}

function warningCount(warning: BillingWarningPayload): number {
  const raw = warning?.count
  const value = typeof raw === 'number' ? raw : Number(raw)

  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0
}

const TEMPLATES: Record<string, WarningTemplate> = {
  period_open: {
    title: 'Месяц не закрыт',
    text: () => 'Часы за этот период ещё можно править, поэтому суммы в счёте могут разойтись с учётом. '
      + 'Выставление за незакрытый месяц разрешает отдельная настройка приложения — если она выключена, сервер откажет.',
    blocking: false,
  },
  already_invoiced: {
    title: 'Часть часов уже выставлена',
    text: (warning) => {
      const count = warningCount(warning)
      const subject = count ? formatRecordsRu(count) : 'Часть записей'

      return `${subject} уже попали в действующий документ и в этот счёт не войдут. `
        + 'Один и тот же час не уходит в счёт дважды — это и есть учёт выставленного.'
    },
    blocking: false,
  },
  no_rate: {
    title: 'Нет ставки',
    text: (warning) => {
      const count = warningCount(warning)
      const subject = count ? `Не нашлась ставка для ${formatRecordsRu(count)}` : 'У части часов не нашлась ставка'

      return `${subject}: ни в снимке списания, ни в карточке проекта. `
        + 'Такие строки уйдут с нулевой ценой — проверьте цену руками или заполните ставку в проекте.'
    },
    blocking: false,
  },
  mixed_companies: {
    title: 'В отборе несколько клиентов',
    text: () => 'Документ выставляется на одного клиента. Уточните отбор: выберите клиента в фильтре '
      + 'или сузьте список проектов, чтобы в нём остался один заказчик.',
    blocking: true,
  },
}

/**
 * Неизвестный код — не повод промолчать.
 *
 * Бэкенд пишется параллельно и может завести новое предупреждение раньше,
 * чем фронт узнает его код. Показываем серверный message, если он есть, и
 * сам код — иначе человек увидит пустую плашку и решит, что всё в порядке.
 * Такое предупреждение не блокирует: блокировку по незнакомому коду фронт
 * придумывать не вправе, отказ всё равно придёт с сервера.
 */
export function describeBillingWarning(warning: BillingWarningPayload | null | undefined): BillingWarningView {
  const code = String(warning?.code || '').trim()
  const template = TEMPLATES[code]
  // Сервер вправе сказать про блокировку сам: решает он, и его ответ
  // главнее нашей таблицы кодов. Флага нет — судим по коду.
  const serverBlocking = typeof warning?.blocking === 'boolean' ? warning.blocking : null

  if (template) {
    return {
      code,
      title: template.title,
      text: String(warning?.message || '').trim() || template.text(warning || {}),
      blocking: serverBlocking === null ? template.blocking : serverBlocking,
    }
  }

  const message = String(warning?.message || '').trim()

  return {
    code: code || 'unknown',
    title: 'Предупреждение',
    text: message || `Сервер сообщил о предупреждении «${code || 'без кода'}». Проверьте отбор перед выставлением.`,
    blocking: serverBlocking === true,
  }
}

export function describeBillingWarnings(
  warnings: BillingWarningPayload[] | null | undefined
): BillingWarningView[] {
  if (!Array.isArray(warnings)) {
    return []
  }

  return warnings.map(describeBillingWarning)
}

/** Есть ли среди предупреждений блокирующее (сегодня — только mixed_companies). */
export function hasBlockingBillingWarning(
  warnings: BillingWarningPayload[] | null | undefined
): boolean {
  return describeBillingWarnings(warnings).some(warning => warning.blocking)
}

/** Блокеры и мягкие предупреждения раздельно — их нельзя показывать одним списком. */
export function splitBillingWarnings(warnings: BillingWarningPayload[] | null | undefined): {
  blockers: BillingWarningView[]
  notices: BillingWarningView[]
} {
  const all = describeBillingWarnings(warnings)

  return {
    blockers: all.filter(warning => warning.blocking),
    notices: all.filter(warning => !warning.blocking),
  }
}
