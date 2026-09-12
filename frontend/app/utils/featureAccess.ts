/**
 * Доступ к платной функции портала — один разбор на все функции.
 *
 * Источник — GET /api/features: по записи на код функции (bdds, billing,
 * roles). Прежние поля state (on | trial | off) и trial_until сервер отдаёт
 * как раньше; к ним добавлены тариф и срок:
 *
 *   access          full | read_only | none
 *   status          active | grace | trial | expired | off
 *   paid_until, grace_until, writable_until, price_month_rub
 *
 * Правило сервера (billing_features.resolve_subscription): после paid_until
 * ещё 7 дней грейса с полной работой, затем «только чтение» — создание и
 * изменение закрыты, просмотр и выгрузки работают. Пробный период после
 * срока — сразу «только чтение». Без тарифа — функция закрыта.
 *
 * Отсюда три исхода для экрана:
 *   - enabled && canWrite  — всё работает;
 *   - enabled && readOnly  — экран открыт, кнопки создания и изменения скрыты,
 *                            сверху плашка «Pro закончился»;
 *   - locked               — замок и карточка «Подключить Pro».
 *
 * Ролевая модель (roles) — особый случай: при окончании Pro у неё закрыты
 * только назначение и правка ролей, а назначенные ограничения ПРОДОЛЖАЮТ
 * действовать (иначе неоплата открыла бы всем ставки и деньги). Решать,
 * применять ли ограничения, — по restrictionsActive, а не по canWrite или
 * enabled: restrictionsActive не зависит даже от аварийного выключателя.
 *
 * Интерфейс ничего не охраняет: гейт на сервере (@feature_required). Здесь
 * только забота о человеке — не показывать кнопок, которые откажут.
 *
 * Старые ответы без access тоже понятны: access выводится из state.
 */

import { formatDaysRu } from './billingFormat'
import { PAID_FEATURE_BADGE, PAID_FEATURE_HINT } from './paidFeatures'
import { formatPlanDate, nextPlanDay, proPriceText, PRO_PRICE_MONTH_RUB } from './proPlan'
import type { BillingFeatureState, PortalFeaturesPayload } from '~/types/billing'

export type FeatureAccessLevel = 'full' | 'read_only' | 'none'
export type PlanStatus = 'active' | 'grace' | 'trial' | 'expired' | 'off'

/** Разобранное состояние одной функции портала. */
export type PortalFeatureInfo = {
  state: BillingFeatureState
  /** Дата окончания пробного периода «ГГГГ-ММ-ДД» либо null. */
  trialUntil: string | null
  access: FeatureAccessLevel
  status: PlanStatus
  /** Оплачено по (включительно) либо null — бессрочно или не оплачивалось. */
  paidUntil: string | null
  /** Последний день грейса после оплаты либо null. */
  graceUntil: string | null
  priceMonthRub: number
  /**
   * Действуют ли ограничения функции (ролевая модель): при действующем Pro и
   * в «только чтении». Сервер присылает restrictions_active для roles; для
   * остальных — выводится из access.
   */
  restrictionsActive: boolean
}

const OFF_FEATURE: PortalFeatureInfo = {
  state: 'off',
  trialUntil: null,
  access: 'none',
  status: 'off',
  paidUntil: null,
  graceUntil: null,
  priceMonthRub: PRO_PRICE_MONTH_RUB,
  restrictionsActive: false,
}

/**
 * Чужое или отсутствующее значение state — это 'off'.
 *
 * Безопасное значение по умолчанию: интерфейс, который при непонятном ответе
 * открывает платный экран, ошибается в сторону ложного обещания.
 */
export function normalizeFeatureState(raw: unknown): BillingFeatureState {
  const value = String(raw ?? '').trim().toLowerCase()

  return value === 'on' || value === 'trial' ? value : 'off'
}

function normalizeAccess(raw: unknown, state: BillingFeatureState): FeatureAccessLevel {
  const value = String(raw ?? '').trim().toLowerCase()
  if (value === 'full' || value === 'read_only' || value === 'none') {
    return value
  }

  return state === 'off' ? 'none' : 'full'
}

function normalizeStatus(raw: unknown, state: BillingFeatureState, access: FeatureAccessLevel): PlanStatus {
  const value = String(raw ?? '').trim().toLowerCase()
  if (value === 'active' || value === 'grace' || value === 'trial' || value === 'expired' || value === 'off') {
    return value
  }

  if (access === 'read_only') {
    return 'expired'
  }

  return state === 'on' ? 'active' : state
}

function readDay(raw: unknown): string | null {
  const value = String(raw ?? '').trim()

  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

/** Ответ /api/features -> состояния по кодам. Мусор превращается в «выключено». */
export function parsePortalFeatures(raw: unknown): Record<string, PortalFeatureInfo> {
  const result: Record<string, PortalFeatureInfo> = {}

  if (!raw || typeof raw !== 'object') {
    return result
  }

  for (const [code, value] of Object.entries(raw as PortalFeaturesPayload)) {
    if (!code) {
      continue
    }

    const payload = (value && typeof value === 'object') ? value : {}
    const state = normalizeFeatureState(payload.state)
    const access = normalizeAccess(payload.access, state)
    const price = Number(payload.price_month_rub)

    result[code] = {
      state,
      trialUntil: readDay(payload.trial_until),
      access,
      status: normalizeStatus(payload.status, state, access),
      paidUntil: readDay(payload.paid_until),
      graceUntil: readDay(payload.grace_until),
      priceMonthRub: Number.isFinite(price) && price > 0 ? price : PRO_PRICE_MONTH_RUB,
      restrictionsActive: typeof payload.restrictions_active === 'boolean'
        ? payload.restrictions_active
        : access !== 'none',
    }
  }

  return result
}

/** Состояние одной функции. Не пришла — считаем выключенной. */
export function readPortalFeature(
  features: Record<string, PortalFeatureInfo> | null | undefined,
  code: string
): PortalFeatureInfo {
  return features?.[code] || { ...OFF_FEATURE }
}

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * Сколько полных дней осталось до даты.
 *
 * В КАЛЕНДАРНЫХ днях: человеку важно «осталось 3 дня», а не «2,4 дня».
 * Сегодняшняя дата — 0 («последний день»), вчерашняя — отрицательное число.
 * null — срок не задан.
 */
export function trialDaysLeft(
  trialUntil: string | null | undefined,
  now: Date = new Date()
): number | null {
  const raw = String(trialUntil || '').trim().slice(0, 10)
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/)

  if (!match) {
    return null
  }

  const endMs = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  const nowMs = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())

  return Math.round((endMs - nowMs) / DAY_MS)
}

/** Бейдж пробного периода. */
export function trialBadgeText(daysLeft: number | null): string | null {
  if (daysLeft === null) {
    return 'пробный период'
  }

  if (daysLeft < 0) {
    return 'пробный период истёк'
  }

  if (daysLeft === 0) {
    return 'пробный, последний день'
  }

  return `пробный, осталось ${formatDaysRu(daysLeft)}`
}

/** Бейдж функции, которая открыта только на чтение. */
export const READ_ONLY_BADGE = 'Pro закончился'
/** Бейдж грейса: всё работает, но оплата просрочена. */
export const GRACE_BADGE = 'продлите Pro'

/** Плашка над экраном функции: срок и что будет дальше. */
export type PlanNotice = {
  tone: 'warning' | 'danger'
  title: string
  text: string
}

export type FeatureAccess = {
  /** Состояние с сервера в прежнем словаре. 'off' — в том числе без ответа. */
  state: BillingFeatureState
  status: PlanStatus
  access: FeatureAccessLevel
  /** Экран функции открыт (полностью или только на чтение). */
  enabled: boolean
  /** Можно создавать и изменять. */
  canWrite: boolean
  /** Экран открыт только на чтение: тариф закончился. */
  readOnly: boolean
  /** Рисовать замок и карточку «Подключить Pro». */
  locked: boolean
  /** Дней до конца пробного периода либо null. */
  trialDaysLeft: number | null
  /** Бейдж у пункта меню и в шапке экрана. */
  badge: string | null
  /** Короткая подсказка «что делать», если функция закрыта. */
  hint: string | null
  /** Плашка над открытым экраном (грейс, «только чтение») либо null. */
  notice: PlanNotice | null
  /**
   * Применять ли ограничения (ролевая модель). true и в «только чтении»:
   * закрыто только изменение ролей. Аварийный выключатель на это не влияет —
   * он закрывает экраны, а не снимает ограничения.
   */
  restrictionsActive: boolean
  /** «3000 ₽ в месяц за портал». */
  priceText: string
  /** Ответ /api/features ещё не получен: состояние — предположение. */
  unknown: boolean
}

function buildNotice(
  feature: PortalFeatureInfo,
  code: string,
  title: string,
  daysLeft: number | null
): PlanNotice | null {
  if (feature.access === 'read_only' && code === 'roles') {
    return {
      tone: 'danger',
      title: 'Тариф Pro закончился — роли не меняются',
      text: 'Назначать и править роли нельзя, пока Pro не продлён. Уже назначенные ограничения продолжают '
        + `действовать: ставки и деньги видят те же сотрудники, что и раньше. Продлить — ${proPriceText(feature.priceMonthRub)}.`,
    }
  }

  if (feature.access === 'read_only') {
    const closedSince = feature.graceUntil
      ? nextPlanDay(feature.graceUntil)
      : feature.trialUntil ? nextPlanDay(feature.trialUntil) : null
    const since = closedSince ? ` с ${formatPlanDate(closedSince)}` : ''

    return {
      tone: 'danger',
      title: 'Тариф Pro закончился — только просмотр',
      text: `Создание и изменение в «${title}» закрыты${since}. Просмотр и выгрузки работают, данные на месте. `
        + `Чтобы снова вносить данные, продлите Pro: ${proPriceText(feature.priceMonthRub)}.`,
    }
  }

  if (feature.access === 'full' && feature.status === 'grace') {
    const until = formatPlanDate(feature.graceUntil)

    return {
      tone: 'warning',
      title: 'Оплата Pro просрочена',
      text: `Всё работает${until ? ` до ${until} включительно` : ''}. Потом создание и изменение закроются, `
        + 'а просмотр и выгрузки останутся.',
    }
  }

  if (feature.access === 'full' && feature.status === 'trial' && daysLeft !== null && daysLeft <= 3) {
    const until = formatPlanDate(feature.trialUntil)

    return {
      tone: 'warning',
      title: daysLeft <= 0 ? 'Сегодня последний день пробного периода' : `Пробный период заканчивается ${until}`,
      text: 'После него создание и изменение закроются, а просмотр и выгрузки останутся. '
        + `Подключить Pro — ${proPriceText(feature.priceMonthRub)}.`,
    }
  }

  return null
}

/**
 * Доступ к функции по коду.
 *
 * flagEnabled — аварийный выключатель из featureFlags: закрыть функцию он
 * может, открыть вопреки серверу — нет.
 */
export function resolveFeatureAccess(options: {
  features: Record<string, PortalFeatureInfo> | null | undefined
  code: string
  /** Название функции для текстов плашки. */
  title: string
  flagEnabled: boolean
  now?: Date
}): FeatureAccess {
  const unknown = !options.features
  const feature = readPortalFeature(options.features, options.code)
  const daysLeft = feature.status === 'trial' && feature.access === 'full'
    ? trialDaysLeft(feature.trialUntil, options.now || new Date())
    : null

  const enabled = options.flagEnabled && feature.access !== 'none'
  const canWrite = options.flagEnabled && feature.access === 'full'
  const readOnly = enabled && !canWrite

  let badge: string | null = null
  if (!enabled) {
    badge = PAID_FEATURE_BADGE
  } else if (readOnly) {
    badge = READ_ONLY_BADGE
  } else if (feature.status === 'grace') {
    badge = GRACE_BADGE
  } else if (feature.status === 'trial') {
    badge = trialBadgeText(daysLeft)
  }

  return {
    state: feature.state,
    status: feature.status,
    access: feature.access,
    enabled,
    canWrite,
    readOnly,
    locked: !enabled,
    trialDaysLeft: daysLeft,
    badge,
    hint: enabled ? null : PAID_FEATURE_HINT,
    notice: enabled ? buildNotice(feature, options.code, options.title, daysLeft) : null,
    restrictionsActive: feature.restrictionsActive,
    priceText: proPriceText(feature.priceMonthRub),
    unknown,
  }
}
