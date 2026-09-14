/**
 * Покупка Pro: разбор ответов сервера, проверки формы, тексты состояний.
 *
 * Макет — docs/design-options/2026-09-12-pro-purchase-mockup.html (ветка
 * claude/pro-mockup). Сервер — backends/python/api/main/pro_purchase_*.py.
 *
 * Разделение труда:
 *  - СУММЫ считает только сервер (GET /api/pro/offer отдаёт готовые суммы по
 *    каждому сроку): здесь их только показывают. Второй расчёт на клиенте
 *    разошёлся бы со счётом при первой правке НДС или скидок;
 *  - ПРОВЕРКИ полей — те же правила, что на сервере
 *    (pro_purchase_pricing.validate_purchase_form), плюс предупреждения,
 *    которых на сервере нет: контрольная цифра ИНН и индекс в адресе;
 *  - ПОРТАЛ заявки клиент не передаёт вообще: сервер берёт его из авторизации.
 *
 * Всё чистыми функциями и без Vue: node:test через tsx не резолвит .vue.
 */

import { formatPlanDate } from './proPlan'
import type { PortalFeatureInfo } from './featureAccess'

const NBSP = '\u00A0'

export const PRO_BUY_LABEL = 'Купить Pro'
export const PRO_RENEW_LABEL = 'Продлить Pro'
export const PRO_SUBMIT_LABEL = 'Сформировать счёт'
export const PRO_CARD_EMAIL_DEFAULT = 'timesheet@mainsoft.su'
export const PAYMENT_PURPOSE_LIMIT = 210
/** За сколько дней до конца оплаты кнопка меню становится «Продлить». */
export const PRO_RENEW_WARNING_DAYS = 7

// ---------------------------------------------------------------------------
// Типы ответа сервера
// ---------------------------------------------------------------------------

export type ProVatMode = 'none' | 'included' | 'on_top'

export type ProTerm = {
  months: number
  label: string
  priceMonth: number
  base: number
  discount: number
  subtotal: number
  vatMode: ProVatMode
  vatRate: number
  vat: number
  total: number
  perMonth: number
  vatText: string
}

export type ProRequestStatus = 'draft' | 'pending' | 'sent' | 'paid' | 'cancelled'
export type ProCrmState = 'sent' | 'retry' | 'manual' | 'none'

export type ProRequestView = {
  id: string
  invoiceNumber: string
  invoiceDate: string
  dueDate: string
  status: ProRequestStatus
  months: number
  monthsText: string
  total: number
  requestedByName: string
  createdAt: string | null
  proPaidUntil: string | null
  /** false — сотруднику без права сервер прислал заявку без реквизитов. */
  full: boolean
  amounts: {
    base: number
    discount: number
    subtotal: number
    vatMode: ProVatMode
    vatRate: number
    vat: number
    total: number
    vatText: string
  } | null
  paymentPurpose: string
  portal: { domain: string, code: string, memberIdShort: string } | null
  payer: { type: 'org' | 'ip', inn: string, kpp: string, name: string, address: string } | null
  contact: { name: string, email: string, cc: string, phone: string } | null
  crmState: ProCrmState
  pdfAvailable: boolean
  paidOn: string | null
  cancelReason: string
  sequenceNumber: number | null
}

export type ProOffer = {
  priceMonthRub: number
  vatMode: ProVatMode
  vatRate: number
  terms: ProTerm[]
  defaultMonths: number
  dueBusinessDays: number
  contactEmail: string
  offerUrl: string
  portal: { domain: string, code: string, memberIdShort: string }
  contact: { name: string, email: string }
  subscription: {
    status: string
    access: string
    paidUntil: string | null
    trialUntil: string | null
    graceUntil: string | null
  }
  canRequest: boolean
  managers: string[]
  currentRequest: ProRequestView | null
  crmMode: 'auto' | 'manual'
}

export type ProRequisite = {
  companyId: string
  companyTitle: string
  payerType: 'org' | 'ip'
  inn: string
  kpp: string
  name: string
  address: string
}

// ---------------------------------------------------------------------------
// Разбор
// ---------------------------------------------------------------------------

type Raw = Record<string, unknown>

function asObject(value: unknown): Raw {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Raw : {}
}

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value)

  return Number.isFinite(parsed) ? parsed : fallback
}

function day(value: unknown): string | null {
  const raw = text(value)

  return /^\d{4}-\d{2}-\d{2}/.test(raw) ? raw.slice(0, 10) : null
}

function vatMode(value: unknown): ProVatMode {
  const raw = text(value)

  return raw === 'included' || raw === 'on_top' ? raw : 'none'
}

const STATUSES: ProRequestStatus[] = ['draft', 'pending', 'sent', 'paid', 'cancelled']
const CRM_STATES: ProCrmState[] = ['sent', 'retry', 'manual', 'none']

export function parseProTerm(raw: unknown): ProTerm | null {
  const item = asObject(raw)
  const months = Math.trunc(num(item.months))
  if (months <= 0) {
    return null
  }

  return {
    months,
    label: text(item.label),
    priceMonth: num(item.price_month),
    base: num(item.base),
    discount: num(item.discount),
    subtotal: num(item.subtotal),
    vatMode: vatMode(item.vat_mode),
    vatRate: num(item.vat_rate),
    vat: num(item.vat),
    total: num(item.total),
    perMonth: num(item.per_month),
    vatText: text(item.vat_text),
  }
}

export function parseProRequest(raw: unknown): ProRequestView | null {
  const item = asObject(raw)
  const id = text(item.id)
  const invoiceNumber = text(item.invoice_number)
  if (!id || !invoiceNumber) {
    return null
  }

  const status = STATUSES.includes(item.status as ProRequestStatus) ? item.status as ProRequestStatus : 'pending'
  const amounts = asObject(item.amounts)
  const portal = asObject(item.portal)
  const payer = asObject(item.payer)
  const contact = asObject(item.contact)
  const full = Boolean(item.payer)

  return {
    id,
    invoiceNumber,
    invoiceDate: day(item.invoice_date) || '',
    dueDate: day(item.due_date) || '',
    status,
    months: Math.trunc(num(item.months)),
    monthsText: text(item.months_text) || monthsText(num(item.months)),
    total: num(item.total),
    requestedByName: text(item.requested_by_name),
    createdAt: text(item.created_at) || null,
    proPaidUntil: day(item.pro_paid_until),
    full,
    amounts: item.amounts
      ? {
          base: num(amounts.base),
          discount: num(amounts.discount),
          subtotal: num(amounts.subtotal),
          vatMode: vatMode(amounts.vat_mode),
          vatRate: num(amounts.vat_rate),
          vat: num(amounts.vat),
          total: num(amounts.total),
          vatText: text(amounts.vat_text),
        }
      : null,
    paymentPurpose: text(item.payment_purpose),
    portal: item.portal
      ? { domain: text(portal.domain), code: text(portal.code), memberIdShort: text(portal.member_id_short) }
      : null,
    payer: full
      ? {
          type: text(payer.type) === 'ip' ? 'ip' : 'org',
          inn: text(payer.inn),
          kpp: text(payer.kpp),
          name: text(payer.name),
          address: text(payer.address),
        }
      : null,
    contact: item.contact
      ? { name: text(contact.name), email: text(contact.email), cc: text(contact.cc), phone: text(contact.phone) }
      : null,
    crmState: CRM_STATES.includes(item.crm_state as ProCrmState) ? item.crm_state as ProCrmState : 'none',
    pdfAvailable: item.pdf_available === true,
    paidOn: day(item.paid_on),
    cancelReason: text(item.cancel_reason),
    sequenceNumber: Number.isFinite(Number(item.sequence_number)) && item.sequence_number !== undefined
      ? Number(item.sequence_number)
      : null,
  }
}

export function parseProOffer(raw: unknown): ProOffer {
  const item = asObject(raw)
  const vat = asObject(item.vat)
  const portal = asObject(item.portal)
  const contact = asObject(item.contact)
  const subscription = asObject(item.subscription)
  const terms = (Array.isArray(item.terms) ? item.terms : [])
    .map(parseProTerm)
    .filter((term): term is ProTerm => term !== null)
  const defaultMonths = Math.trunc(num(item.default_months))

  return {
    priceMonthRub: num(item.price_month_rub, 3000),
    vatMode: vatMode(vat.mode),
    vatRate: num(vat.rate),
    terms,
    defaultMonths: terms.some(term => term.months === defaultMonths)
      ? defaultMonths
      : (terms[terms.length - 1]?.months ?? 12),
    dueBusinessDays: Math.trunc(num(item.due_business_days, 5)),
    contactEmail: text(item.contact_email) || PRO_CARD_EMAIL_DEFAULT,
    offerUrl: text(item.offer_url).startsWith('https://') ? text(item.offer_url) : '',
    portal: { domain: text(portal.domain), code: text(portal.code), memberIdShort: text(portal.member_id_short) },
    contact: { name: text(contact.name), email: text(contact.email) },
    subscription: {
      status: text(subscription.status) || 'off',
      access: text(subscription.access) || 'none',
      paidUntil: day(subscription.paid_until),
      trialUntil: day(subscription.trial_until),
      graceUntil: day(subscription.grace_until),
    },
    canRequest: item.can_request === true,
    managers: (Array.isArray(item.managers) ? item.managers : []).map(text).filter(Boolean),
    currentRequest: parseProRequest(item.current_request),
    crmMode: text(item.crm_mode) === 'auto' ? 'auto' : 'manual',
  }
}

export function parseProRequisite(raw: unknown): ProRequisite | null {
  const item = asObject(raw)
  const inn = text(item.inn)
  if (!/^\d{10}$|^\d{12}$/.test(inn)) {
    return null
  }

  return {
    companyId: text(item.company_id),
    companyTitle: text(item.company_title),
    payerType: inn.length === 12 ? 'ip' : 'org',
    inn,
    kpp: inn.length === 12 ? '' : text(item.kpp),
    name: text(item.name),
    address: text(item.address),
  }
}

// ---------------------------------------------------------------------------
// Формат
// ---------------------------------------------------------------------------

export function pluralRu(count: number, one: string, few: string, many: string): string {
  const value = Math.abs(Math.trunc(count))
  const lastTwo = value % 100
  const last = value % 10
  if (lastTwo > 10 && lastTwo < 20) {
    return many
  }
  if (last === 1) {
    return one
  }
  if (last > 1 && last < 5) {
    return few
  }

  return many
}

export function monthsText(months: number): string {
  const value = Math.trunc(months)

  return `${value} ${pluralRu(value, 'месяц', 'месяца', 'месяцев')}`
}

export function daysText(days: number): string {
  const value = Math.trunc(days)

  return `${value} ${pluralRu(value, 'день', 'дня', 'дней')}`
}

function groupThousands(integer: string | undefined): string {
  return String(integer || '0').replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
}

/** «30 000 ₽» — целые рубли; копейки, если они есть. */
export function formatRub(value: number): string {
  const amount = Math.round(num(value) * 100) / 100
  const [integer, fraction] = Math.abs(amount).toFixed(2).split('.')
  const sign = amount < 0 ? '−' : ''
  const kopecks = fraction === '00' ? '' : `,${fraction}`

  return `${sign}${groupThousands(integer)}${kopecks}${NBSP}₽`
}

/** «5 409,84» — всегда с копейками, как в счёте. */
export function formatRubKop(value: number): string {
  const [integer, fraction] = Math.abs(num(value)).toFixed(2).split('.')

  return `${groupThousands(integer)},${fraction}`
}

export function vatSummaryText(term: Pick<ProTerm, 'vatMode' | 'vatRate' | 'vat'>): string {
  if (term.vatMode === 'none' || term.vatRate <= 0) {
    return 'не облагается'
  }
  const prefix = term.vatMode === 'included' ? 'в т.ч. ' : '+'

  return `${prefix}${formatRubKop(term.vat)}${NBSP}₽`
}

/** Строки сводки справа от формы: база, скидка, НДС. */
export function termSummaryRows(term: ProTerm): Array<{ label: string, value: string, discount?: boolean }> {
  const rows: Array<{ label: string, value: string, discount?: boolean }> = [
    { label: `${monthsText(term.months)} × ${formatRub(term.priceMonth)}`, value: formatRub(term.base) },
  ]
  if (term.discount > 0) {
    const label = term.label.includes('по цене') ? `«${term.label}»` : term.label
    rows.push({ label: `Скидка ${label}`.trim(), value: `−${formatRub(term.discount)}`, discount: true })
  }
  const rate = term.vatRate > 0 ? ` ${term.vatRate}%` : ''
  rows.push({ label: `НДС${term.vatMode === 'none' ? '' : rate}`, value: vatSummaryText(term) })

  return rows
}

/** Подпись под итогом: цена в месяц или намёк на годовую скидку. */
export function perMonthHint(term: ProTerm, terms: ProTerm[]): string {
  if (term.months > 1) {
    return `Это ${formatRub(term.perMonth)} в месяц за весь портал`
  }
  const best = [...terms].sort((a, b) => a.perMonth - b.perMonth)[0]
  if (best && best.months > 1 && best.perMonth < term.perMonth) {
    const free = Math.round(best.months - best.total / term.total)

    return free > 0
      ? `Выгоднее за ${monthsText(best.months)}: ${monthsText(free)} бесплатно`
      : `Выгоднее за ${monthsText(best.months)}`
  }

  return 'Цена за весь портал, без ограничения по сотрудникам'
}

/** Подпись под суммой в карточке срока. */
export function termCardHint(term: ProTerm): string {
  return term.discount > 0 ? `${formatRub(term.perMonth)} в месяц` : 'без скидки'
}

export function cardPaymentMailto(options: {
  email: string
  domain: string
  code: string
  term: ProTerm | null
}): string {
  const email = options.email || PRO_CARD_EMAIL_DEFAULT
  const subject = `Оплата Pro картой — ${options.domain}, код ${options.code}`
  const lines = [
    'Здравствуйте! Хотим оплатить Pro картой.',
    `Портал: ${options.domain}`,
    `Код портала: ${options.code}`,
  ]
  if (options.term) {
    lines.push(`Срок: ${monthsText(options.term.months)}`, `Сумма: ${formatRub(options.term.total)}`)
  }

  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n'))}`
}

// ---------------------------------------------------------------------------
// Форма и проверки
// ---------------------------------------------------------------------------

export type ProFormField =
  | 'contactName'
  | 'contactPhone'
  | 'payerInn'
  | 'payerKpp'
  | 'payerName'
  | 'payerAddress'
  | 'contactEmail'
  | 'contactCc'
  | 'offerAccepted'
  | 'months'

export type ProForm = {
  contactName: string
  contactPhone: string
  payerInn: string
  payerKpp: string
  payerName: string
  payerAddress: string
  contactEmail: string
  contactCc: string
  offerAccepted: boolean
  months: number
  payerCompanyId: string
}

export const PRO_FORM_FIELDS: ProFormField[] = [
  'contactName', 'contactPhone', 'payerInn', 'payerKpp', 'payerName', 'payerAddress',
  'contactEmail', 'contactCc', 'months', 'offerAccepted',
]

export const PRO_FIELD_LABELS: Record<ProFormField, string> = {
  contactName: 'Кому писать',
  contactPhone: 'Телефон',
  payerInn: 'ИНН',
  payerKpp: 'КПП',
  payerName: 'Наименование',
  payerAddress: 'Юридический адрес',
  contactEmail: 'Почта для счёта',
  contactCc: 'Копия счёта',
  offerAccepted: 'Оферта',
  months: 'Срок подписки',
}

/** Имя поля сервера -> поле формы: ошибки 400 ложатся на те же поля. */
export const PRO_SERVER_FIELDS: Record<string, ProFormField> = {
  contact_name: 'contactName',
  contact_phone: 'contactPhone',
  payer_inn: 'payerInn',
  payer_kpp: 'payerKpp',
  payer_name: 'payerName',
  payer_address: 'payerAddress',
  contact_email: 'contactEmail',
  contact_cc: 'contactCc',
  offer_accepted: 'offerAccepted',
  months: 'months',
}

export function createProForm(offer?: Pick<ProOffer, 'contact' | 'defaultMonths'> | null): ProForm {
  return {
    contactName: offer?.contact.name || '',
    contactPhone: '',
    payerInn: '',
    payerKpp: '',
    payerName: '',
    payerAddress: '',
    contactEmail: offer?.contact.email || '',
    contactCc: '',
    offerAccepted: false,
    months: offer?.defaultMonths || 12,
    payerCompanyId: '',
  }
}

/** Форма из прежней заявки — «поправить реквизиты». */
export function proFormFromRequest(request: ProRequestView, fallback: ProForm): ProForm {
  if (!request.payer || !request.contact) {
    return fallback
  }

  return {
    ...fallback,
    contactName: request.contact.name,
    contactPhone: request.contact.phone,
    contactEmail: request.contact.email,
    contactCc: request.contact.cc,
    payerInn: request.payer.inn,
    payerKpp: request.payer.kpp,
    payerName: request.payer.name,
    payerAddress: request.payer.address,
    months: request.months || fallback.months,
  }
}

export const normalizeInnInput = (value: unknown): string => String(value ?? '').replace(/\s+/g, '')
export const normalizeKppInput = (value: unknown): string => String(value ?? '').replace(/\s+/g, '').toUpperCase()

export function payerTypeForInn(inn: string): 'org' | 'ip' {
  return normalizeInnInput(inn).length === 12 ? 'ip' : 'org'
}

/** Контрольные цифры ИНН (алгоритм ФНС). Только для предупреждения. */
export function innChecksumOk(value: string): boolean {
  const inn = normalizeInnInput(value)
  if (!/^\d+$/.test(inn)) {
    return false
  }
  const digits = inn.split('').map(Number)
  const check = (weights: number[]) => weights.reduce((sum, weight, index) => sum + weight * digits[index]!, 0) % 11 % 10
  if (inn.length === 10) {
    return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) === digits[9]
  }
  if (inn.length === 12) {
    return check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === digits[10]
      && check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === digits[11]
  }

  return false
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const KPP_RE = /^\d{4}[0-9A-Z]{2}\d{3}$/

export type ProFieldCheck = { error: string, warning: string }

export function checkProField(field: ProFormField, form: ProForm, termMonths: number[] = []): ProFieldCheck {
  const result: ProFieldCheck = { error: '', warning: '' }
  const isIp = payerTypeForInn(form.payerInn) === 'ip'

  switch (field) {
    case 'payerInn': {
      const inn = normalizeInnInput(form.payerInn)
      if (!inn) {
        result.error = 'Укажите ИНН плательщика'
      } else if (!/^\d+$/.test(inn)) {
        result.error = 'В ИНН только цифры'
      } else if (inn.length !== 10 && inn.length !== 12) {
        result.error = `У организации 10 цифр, у ИП — 12. Сейчас ${inn.length}`
      } else if (!innChecksumOk(inn)) {
        result.warning = 'Контрольная цифра не сходится — проверьте ИНН. Счёт сформировать можно'
      }
      break
    }
    case 'payerKpp': {
      const kpp = normalizeKppInput(form.payerKpp)
      if (!isIp) {
        if (!kpp) {
          result.error = 'Укажите КПП — у организации он обязателен'
        } else if (!KPP_RE.test(kpp)) {
          result.error = 'КПП — 9 знаков: 4 цифры, 2 цифры или заглавные латинские буквы, 3 цифры'
        }
      }
      break
    }
    case 'payerName':
      if (form.payerName.trim().length < 3) {
        result.error = isIp ? 'Укажите ФИО предпринимателя' : 'Укажите полное наименование организации'
      }
      break
    case 'payerAddress': {
      const address = form.payerAddress.trim()
      if (address.length < 10) {
        result.error = 'Укажите юридический адрес'
      } else if (!/(^|\D)\d{6}(\D|$)/.test(address)) {
        result.warning = 'Не видно индекса — добавьте, если знаете'
      }
      break
    }
    case 'contactEmail': {
      const email = form.contactEmail.trim()
      if (!email) {
        result.error = 'Укажите почту, на которую отправить счёт'
      } else if (!EMAIL_RE.test(email)) {
        result.error = 'Почта выглядит неполной: нужен вид name@company.ru'
      }
      break
    }
    case 'contactCc': {
      const cc = form.contactCc.trim()
      if (cc && !EMAIL_RE.test(cc)) {
        result.error = 'Проверьте адрес копии или оставьте поле пустым'
      }
      break
    }
    case 'contactPhone': {
      const phone = form.contactPhone.trim()
      if (phone) {
        const digits = phone.replace(/\D/g, '')
        if (digits.length < 10 || digits.length > 11) {
          result.error = 'Телефон: 10–11 цифр, например +7 842 250-14-80'
        }
      }
      break
    }
    case 'contactName':
      if (form.contactName.trim().length < 2) {
        result.error = 'Укажите, кому писать по счёту'
      }
      break
    case 'offerAccepted':
      if (!form.offerAccepted) {
        result.error = 'Отметьте согласие с условиями оферты'
      }
      break
    case 'months':
      if (termMonths.length && !termMonths.includes(form.months)) {
        result.error = 'Выберите срок подписки'
      }
      break
  }

  return result
}

export type ProFormErrors = Partial<Record<ProFormField, string>>

/** Все ошибки формы по порядку полей; у ИП поле КПП не проверяется. */
export function validateProForm(form: ProForm, termMonths: number[] = []): Array<{ field: ProFormField, error: string }> {
  return PRO_FORM_FIELDS
    .filter(field => !(field === 'payerKpp' && payerTypeForInn(form.payerInn) === 'ip'))
    .map(field => ({ field, error: checkProField(field, form, termMonths).error }))
    .filter(item => item.error)
}

export function errorSummaryTitle(count: number): string {
  return `Счёт не сформирован — ${count} ${pluralRu(count, 'поле требует', 'поля требуют', 'полей требуют')} внимания:`
}

/** Тело POST /api/pro/requests. Портала, домена и member_id здесь нет намеренно. */
export function buildProRequestBody(form: ProForm): Record<string, unknown> {
  const inn = normalizeInnInput(form.payerInn)

  return {
    contact_name: form.contactName.trim(),
    contact_phone: form.contactPhone.trim(),
    contact_email: form.contactEmail.trim(),
    contact_cc: form.contactCc.trim(),
    payer_inn: inn,
    payer_kpp: payerTypeForInn(inn) === 'ip' ? '' : normalizeKppInput(form.payerKpp),
    payer_name: form.payerName.trim(),
    payer_address: form.payerAddress.trim(),
    payer_company_id: form.payerCompanyId,
    months: form.months,
    offer_accepted: form.offerAccepted === true,
  }
}

/** Ошибки 400 сервера -> ошибки полей формы. */
export function mapServerFieldErrors(raw: unknown): ProFormErrors {
  const errors = asObject(raw)
  const result: ProFormErrors = {}
  for (const [key, message] of Object.entries(errors)) {
    const field = PRO_SERVER_FIELDS[key]
    if (field && text(message)) {
      result[field] = text(message)
    }
  }

  return result
}

/** Короткое имя плательщика для подсказок: «ООО «Кварц»». */
export function shortPayerName(name: string): string {
  return name
    .replace(/^Общество с ограниченной ответственностью/i, 'ООО')
    .replace(/^Акционерное общество/i, 'АО')
    .replace(/^Индивидуальный предприниматель/i, 'ИП')
    .trim()
}

// ---------------------------------------------------------------------------
// Состояния заявки
// ---------------------------------------------------------------------------

export type ProTone = 'info' | 'success' | 'warning' | 'danger' | 'muted'

export function isOpenProRequest(request: Pick<ProRequestView, 'status'> | null | undefined): boolean {
  return Boolean(request && (request.status === 'draft' || request.status === 'pending' || request.status === 'sent'))
}

export const PRO_REQUEST_STATUS_LABELS: Record<ProRequestStatus, string> = {
  draft: 'Черновик',
  pending: 'Ожидает отправки в CRM',
  sent: 'Счёт выставлен',
  paid: 'Оплачена',
  cancelled: 'Отменена',
}

/** Главная плашка экрана «Счёт сформирован». */
export function describeProRequest(request: ProRequestView, contactEmail = PRO_CARD_EMAIL_DEFAULT): {
  tone: ProTone
  title: string
  text: string
} {
  const due = formatPlanDate(request.dueDate)
  if (request.status === 'paid') {
    const until = formatPlanDate(request.proPaidUntil)

    return {
      tone: 'success',
      title: `Оплата по счёту ${request.invoiceNumber} получена`,
      text: until ? `Pro включён до ${until}.` : 'Pro включён.',
    }
  }
  if (request.status === 'cancelled') {
    return {
      tone: 'muted',
      title: `Заявка ${request.invoiceNumber} отменена`,
      text: request.cancelReason ? `Причина: ${request.cancelReason}.` : 'Счёт по ней недействителен.',
    }
  }
  if (request.crmState === 'manual') {
    return {
      tone: 'warning',
      title: `Заявка ${request.invoiceNumber} сохранена, счёт готовится`,
      text: 'Автоматическая отправка в CRM Mainsoft пока не подключена: заявка ожидает отправки. '
        + `Менеджер выставит счёт вручную в рабочее время и пришлёт его на почту. Вопросы — ${contactEmail}.`,
    }
  }
  if (request.status !== 'sent' || request.crmState === 'retry') {
    return {
      tone: 'warning',
      title: `Заявка ${request.invoiceNumber} сохранена, ожидает отправки в CRM`,
      text: 'Портал Mainsoft не ответил. Заявка у нас, повторим отправку автоматически — счёт придёт на почту.',
    }
  }

  return {
    tone: 'success',
    title: `Счёт № ${request.invoiceNumber} от ${formatPlanDate(request.invoiceDate)} сформирован`,
    text: due ? `Оплатите до ${due}. Pro включим после поступления денег.` : 'Pro включим после поступления денег.',
  }
}

export type ProTimelineStep = { title: string, hint: string, state: 'done' | 'now' | 'todo' }

export function proRequestTimeline(request: ProRequestView): ProTimelineStep[] {
  const invoiceDone = request.status === 'sent' || request.status === 'paid'
  const paid = request.status === 'paid'
  const created = formatPlanDate(request.invoiceDate)
  const steps: ProTimelineStep[] = [
    {
      title: 'Заявка отправлена',
      hint: [created, request.requestedByName].filter(Boolean).join(' · '),
      state: 'done',
    },
    {
      title: invoiceDone ? 'Счёт выставлен' : 'Счёт готовится',
      hint: invoiceDone
        ? `№ ${request.invoiceNumber} на ${formatRub(request.total)}`
        : 'ожидает отправки в CRM Mainsoft',
      state: invoiceDone ? 'done' : 'now',
    },
    {
      title: 'Ждём оплату',
      hint: request.dueDate ? `до ${formatPlanDate(request.dueDate)}. Деньги обычно идут 1–2 рабочих дня` : '',
      state: paid ? 'done' : invoiceDone ? 'now' : 'todo',
    },
    {
      title: 'Оплата получена',
      hint: paid ? formatPlanDate(request.paidOn) : 'менеджер Mainsoft сверит платёж со счётом',
      state: paid ? 'done' : 'todo',
    },
    {
      title: 'Pro включён',
      hint: paid && request.proPaidUntil
        ? `до ${formatPlanDate(request.proPaidUntil)}`
        : 'в течение рабочего дня после поступления денег',
      state: paid ? 'done' : 'todo',
    },
  ]

  return steps
}

// ---------------------------------------------------------------------------
// Кнопка «Купить Pro» в меню и карточка «Подписка»
// ---------------------------------------------------------------------------

/** Разница в днях между датами «ГГГГ-ММ-ДД» (until − today). */
export function daysUntil(until: string | null | undefined, today: string): number | null {
  const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(until || ''))
  const b = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(today || ''))
  if (!a || !b) {
    return null
  }
  const to = Date.UTC(Number(a[1]), Number(a[2]) - 1, Number(a[3]))
  const from = Date.UTC(Number(b[1]), Number(b[2]) - 1, Number(b[3]))

  return Math.round((to - from) / 86_400_000)
}

export function todayIso(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')

  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/**
 * Экраны, где кнопки нет: часы в задаче и отчёты — там Pro не нужен, а реклама
 * мешает работать (макет, экран 1). Страница /pro — сама форма.
 */
const PRO_BUTTON_HIDDEN_PREFIXES = ['/reports', '/pro', '/embedded', '/slider', '/install', '/handler']

export function shouldShowProNavButton(path: string | null | undefined): boolean {
  const normalized = String(path || '/').split('?')[0]!.toLowerCase().replace(/\/+$/, '') || '/'

  return !PRO_BUTTON_HIDDEN_PREFIXES.some(prefix => normalized === prefix || normalized.startsWith(`${prefix}/`))
}

export type ProNavButton = {
  /** Бейдж слева от кнопки (срок пробного, «Pro до …»). */
  badge: string | null
  badgeTone: ProTone
  /** Кнопка; null — кнопки нет (Pro активен). */
  label: string | null
  tone: 'outline' | 'warning' | 'danger' | 'default'
}

export type ProSubscriptionInput = Pick<PortalFeatureInfo, 'status' | 'paidUntil' | 'trialUntil' | 'graceUntil'>

/**
 * Состояние кнопки в меню по тарифу (/api/features) и открытой заявке.
 *
 * features=null — ответа ещё нет: показываем обычное «Купить Pro», это то же
 * самое, что видит портал без тарифа.
 */
export function resolveProNavButton(options: {
  subscription: ProSubscriptionInput | null
  openRequest: boolean
  today: string
}): ProNavButton {
  const { subscription, openRequest, today } = options
  if (openRequest) {
    return { badge: null, badgeTone: 'info', label: 'Счёт ждёт оплаты', tone: 'default' }
  }
  const status = subscription?.status || 'off'
  if (status === 'active') {
    if (!subscription?.paidUntil) {
      return { badge: 'Pro', badgeTone: 'success', label: null, tone: 'default' }
    }
    const left = daysUntil(subscription.paidUntil, today)
    if (left !== null && left <= PRO_RENEW_WARNING_DAYS) {
      return { badge: null, badgeTone: 'warning', label: `${PRO_RENEW_LABEL} · ${Math.max(0, left)} дн.`, tone: 'warning' }
    }

    return { badge: `Pro до ${formatPlanDate(subscription.paidUntil)}`, badgeTone: 'success', label: null, tone: 'default' }
  }
  if (status === 'grace' || status === 'expired') {
    return { badge: null, badgeTone: 'danger', label: 'Pro истёк · продлить', tone: 'danger' }
  }
  if (status === 'trial') {
    const left = daysUntil(subscription?.trialUntil, today)

    return {
      badge: left === null ? 'Пробный Pro' : `Пробный Pro · ${Math.max(0, left)} дн.`,
      badgeTone: left !== null && left <= 3 ? 'warning' : 'info',
      label: PRO_BUY_LABEL,
      tone: 'outline',
    }
  }

  return { badge: null, badgeTone: 'info', label: PRO_BUY_LABEL, tone: 'outline' }
}

/** Подвал раскрытых «Финансов» с ценой: пока Pro не оплачен. */
export function shouldShowFinanceProFooter(subscription: ProSubscriptionInput | null): boolean {
  return !subscription || subscription.status !== 'active'
}

export type ProSubscriptionCard = {
  tone: ProTone
  badge: string
  text: string
  action: string | null
}

/** Карточка «Подписка» в настройках. */
export function describeProSubscription(options: {
  subscription: ProSubscriptionInput | null
  request: Pick<ProRequestView, 'status' | 'invoiceNumber' | 'dueDate' | 'total' | 'monthsText'> | null
  today: string
}): ProSubscriptionCard {
  const { subscription, request, today } = options
  if (request && isOpenProRequest(request)) {
    const due = formatPlanDate(request.dueDate)

    return {
      tone: 'info',
      badge: `Счёт ${request.invoiceNumber} ждёт оплаты${due ? ` до ${due}` : ''}`,
      text: `${request.monthsText}, ${formatRub(request.total)}. Pro включим после поступления денег.`,
      action: 'Открыть счёт',
    }
  }
  const status = subscription?.status || 'off'
  if (status === 'active') {
    if (!subscription?.paidUntil) {
      return { tone: 'success', badge: 'Pro подключён', text: 'Все функции Pro открыты.', action: null }
    }
    const until = formatPlanDate(subscription.paidUntil)
    const left = daysUntil(subscription.paidUntil, today)
    if (left !== null && left <= PRO_RENEW_WARNING_DAYS) {
      return {
        tone: 'warning',
        badge: `Pro до ${until} · осталось ${daysText(Math.max(0, left))}`,
        text: 'Продлите сейчас — новый срок начнётся со следующего дня, оплаченные дни не пропадут.',
        action: PRO_RENEW_LABEL,
      }
    }

    return {
      tone: 'success',
      badge: `Pro активен до ${until}`,
      text: 'Продлить можно заранее: новый срок начнётся со следующего дня после окончания текущего.',
      action: 'Продлить заранее',
    }
  }
  if (status === 'grace') {
    return {
      tone: 'danger',
      badge: `Pro истёк ${formatPlanDate(subscription?.paidUntil)} · запись закроется после ${formatPlanDate(subscription?.graceUntil)}`,
      text: 'Всё работает ещё несколько дней. Потом создание и изменение в БДДС, счетах и ролях закроются, данные и выгрузки останутся.',
      action: PRO_RENEW_LABEL,
    }
  }
  if (status === 'expired') {
    return {
      tone: 'danger',
      badge: 'Pro истёк · только чтение',
      text: 'Данные БДДС и счетов доступны для просмотра и выгрузки, настроенные роли действуют. Создание и изменение закрыты.',
      action: PRO_RENEW_LABEL,
    }
  }
  if (status === 'trial') {
    const left = daysUntil(subscription?.trialUntil, today)
    const until = formatPlanDate(subscription?.trialUntil)

    return {
      tone: 'info',
      badge: until
        ? `Пробный Pro до ${until}${left !== null ? ` · осталось ${daysText(Math.max(0, left))}` : ''}`
        : 'Пробный Pro',
      text: 'Все функции Pro открыты. После пробного периода данные останутся, закроется создание и изменение.',
      action: PRO_BUY_LABEL,
    }
  }

  return {
    tone: 'muted',
    badge: 'Pro не подключён',
    text: 'Базовые функции работают без ограничений. Pro добавляет деньги к часам.',
    action: PRO_BUY_LABEL,
  }
}

// ---------------------------------------------------------------------------
// Ошибки сервера
// ---------------------------------------------------------------------------

export type ProApiErrorView = {
  status: number | null
  code: string
  message: string
  fieldErrors: ProFormErrors
}

const PRO_ERROR_TEXTS: Record<string, string> = {
  pro_request_forbidden: 'Счёт на Pro запрашивает администратор портала или сотрудник с ролью «Бухгалтерия».',
  validation_failed: 'Проверьте отмеченные поля формы.',
  request_paid: 'Счёт уже оплачен — отменить заявку нельзя. Напишите на timesheet@mainsoft.su.',
  pdf_not_ready: 'PDF счёта ещё не готов — пришлём его на почту.',
  pdf_unavailable: 'PDF счёта пока не получается скачать — попробуйте через минуту или напишите на timesheet@mainsoft.su.',
  portal_unknown: 'Портал не определён: откройте приложение из Битрикс24 заново.',
}

/** Отказ $api -> текст для человека и ошибки полей. */
export function describeProApiError(error: unknown): ProApiErrorView {
  const candidate = asObject(error) as {
    data?: unknown
    status?: number
    statusCode?: number
    response?: { status?: number }
  }
  const data = asObject(candidate.data)
  const status = candidate.response?.status ?? candidate.status ?? candidate.statusCode ?? null
  const code = text(data.code)
  if (status === 429) {
    return { status, code: 'rate_limited', message: 'Слишком много запросов, попробуйте через минуту.', fieldErrors: {} }
  }
  const message = text(data.error) || PRO_ERROR_TEXTS[code]
    || (status === null ? 'Сервер приложения не ответил. Проверьте соединение и повторите.' : 'Не получилось: ошибка сервера. Повторите позже.')

  return { status, code, message, fieldErrors: mapServerFieldErrors(data.errors) }
}
