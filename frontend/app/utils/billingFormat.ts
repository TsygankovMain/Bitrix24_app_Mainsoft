/**
 * Форматирование денег, часов, дат и периодов для экранов «Счёт и акт».
 *
 * Считаем сами, без Intl и toLocaleString. Причина не в производительности:
 * набор локальных данных у Node и у браузера разный (и у разных сборок Node
 * тоже), поэтому один и тот же вызов toLocaleString('ru-RU') даёт то узкий
 * неразрывный пробел, то обычный, то вообще запятую-разделитель тысяч. В
 * счёте это видно человеку, а в тестах превращается в «работает у меня».
 * Разделитель тысяч здесь всегда неразрывный пробел U+00A0 (сумма не должна
 * переноситься по строке), десятичный — запятая.
 *
 * app/utils/reportFormat.ts не трогаем и не расширяем: там форматирование
 * отчётных часов, у него другая точность (1 знак) и свои потребители.
 */

/** Неразрывный пробел — разделитель разрядов. Ровно один на всё приложение. */
export const NBSP = ' '

/** Символы валют, которые приложение реально видит. Прочее печатаем кодом. */
const CURRENCY_SYMBOLS: Record<string, string> = {
  RUB: '₽',
  USD: '$',
  EUR: '€',
}

function toFiniteNumber(value: unknown): number {
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

/**
 * Число в рублях с копейками, но БЕЗ знака валюты: «12 345,67».
 *
 * Отрицательные суммы возможны (сторно в будущем), поэтому минус выносим
 * перед разрядами, а не оставляем внутри группировки.
 */
export function formatBillingAmount(value: unknown, fractionDigits = 2): string {
  const number = toFiniteNumber(value)
  const isNegative = number < 0
  const fixed = Math.abs(number).toFixed(fractionDigits)
  const [intPart = '0', fractionPart = ''] = fixed.split('.')

  let grouped = ''
  for (let index = 0; index < intPart.length; index += 1) {
    const fromEnd = intPart.length - index
    grouped += intPart[index]
    if (fromEnd > 1 && (fromEnd - 1) % 3 === 0) {
      grouped += NBSP
    }
  }

  const body = fractionPart ? `${grouped},${fractionPart}` : grouped

  return isNegative ? `−${body}` : body
}

/** Сумма со знаком валюты: «12 345,67 ₽». Неизвестная валюта печатается кодом. */
export function formatBillingMoney(value: unknown, currency: string | null | undefined = 'RUB'): string {
  const code = String(currency || 'RUB').trim().toUpperCase()
  const symbol = CURRENCY_SYMBOLS[code] || code

  return `${formatBillingAmount(value)}${NBSP}${symbol}`
}

/**
 * Часы: один знак после запятой, но целое остаётся целым («8», а не «8,0»).
 *
 * В счёте количество попадает в печатную форму, и «8,0 ч» там выглядит как
 * машинный вывод. Дробные же часы обязаны быть видны: 7,5 и 8 — разные деньги.
 */
export function formatBillingHours(value: unknown): string {
  const number = toFiniteNumber(value)
  const rounded = Math.round(number * 10) / 10

  return Number.isInteger(rounded)
    ? formatBillingAmount(rounded, 0)
    : formatBillingAmount(rounded, 1)
}

/** Часы с единицей измерения — для итогов и шапок. */
export function formatBillingHoursWithUnit(value: unknown): string {
  return `${formatBillingHours(value)}${NBSP}ч`
}

/** Дата ДД.ММ.ГГГГ. Принимает «2026-09-12» и ISO с временем. Мусор возвращает как есть. */
export function formatBillingDate(value: string | null | undefined): string {
  const raw = String(value || '').trim()
  if (!raw) {
    return ''
  }

  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) {
    return `${iso[3]}.${iso[2]}.${iso[1]}`
  }

  return raw
}

/**
 * Период документа.
 *
 * Ровный календарный месяц пишем словами («сентябрь 2026»): так период читают
 * и в счёте, и в разговоре. Всё остальное — двумя датами, чтобы не выдавать
 * обрезанный месяц за полный.
 */
const MONTHS_NOMINATIVE = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]

export function formatBillingPeriod(
  from: string | null | undefined,
  to: string | null | undefined
): string {
  const fromIso = String(from || '').trim().slice(0, 10)
  const toIso = String(to || '').trim().slice(0, 10)

  if (!fromIso && !toIso) {
    return ''
  }

  if (!fromIso || !toIso) {
    return formatBillingDate(fromIso || toIso)
  }

  const fromMatch = fromIso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  const toMatch = toIso.match(/^(\d{4})-(\d{2})-(\d{2})$/)

  if (fromMatch && toMatch && fromMatch[1] === toMatch[1] && fromMatch[2] === toMatch[2]) {
    const year = Number(fromMatch[1])
    const month = Number(fromMatch[2])
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()

    if (Number(fromMatch[3]) === 1 && Number(toMatch[3]) === lastDay) {
      return `${MONTHS_NOMINATIVE[month - 1]} ${year}`
    }
  }

  return `${formatBillingDate(fromIso)} — ${formatBillingDate(toIso)}`
}

/**
 * Русское склонение числительного: 1 день, 2 дня, 5 дней.
 *
 * Своя реализация, а не Intl.PluralRules: тот отдаёт категорию ('one'/'few'/
 * 'many'), а не слово, и всё равно требует этой же таблицы форм.
 */
export function pluralizeRu(count: number, forms: [string, string, string]): string {
  const absolute = Math.abs(Math.trunc(count))
  const lastTwo = absolute % 100
  const last = absolute % 10

  if (lastTwo >= 11 && lastTwo <= 14) {
    return forms[2]
  }

  if (last === 1) {
    return forms[0]
  }

  if (last >= 2 && last <= 4) {
    return forms[1]
  }

  return forms[2]
}

/** «5 дней», «1 день» — с самим числом. */
export function formatDaysRu(count: number): string {
  const days = Math.trunc(count)

  return `${days} ${pluralizeRu(days, ['день', 'дня', 'дней'])}`
}

/** «3 записи» — счётчик потреблённых списаний и строк. */
export function formatRecordsRu(count: number): string {
  const records = Math.trunc(count)

  return `${records} ${pluralizeRu(records, ['запись', 'записи', 'записей'])}`
}

/** Подпись статуса документа для таблицы и карточки. */
export function billingStatusLabel(status: string | null | undefined): string {
  switch (String(status || '').trim()) {
    case 'issued':
      return 'Выставлен'
    case 'cancelled':
      return 'Отменён'
    default:
      return 'Неизвестен'
  }
}

/** Классы бейджа статуса. Держим рядом с подписью, чтобы не разъезжались. */
export function billingStatusClass(status: string | null | undefined): string {
  switch (String(status || '').trim()) {
    case 'issued':
      return 'bg-emerald-50 text-emerald-700'
    case 'cancelled':
      return 'bg-slate-100 text-slate-500'
    default:
      return 'bg-amber-50 text-amber-700'
  }
}

/** Номер документа для таблицы: номер портала, иначе внутренний id. */
export function billingDocumentNumber(document: {
  crm_account_number?: string | null
  id?: number | string | null
} | null | undefined): string {
  const number = String(document?.crm_account_number || '').trim()
  if (number) {
    return number
  }

  const id = String(document?.id ?? '').trim()

  return id ? `#${id}` : '—'
}
