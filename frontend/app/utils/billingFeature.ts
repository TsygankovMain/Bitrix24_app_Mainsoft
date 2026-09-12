/**
 * Подписка на «Счёт и акт» и права в интерфейсе.
 *
 * Состояние функции приходит с сервера: GET /api/features отдаёт
 * {"billing": {"state": "on"|"trial"|"off", "trial_until": ...}} (контракт,
 * раздел «Эндпоинты»). Фронтовый флаг FINANCE_BILLING_ENABLED остаётся
 * АВАРИЙНЫМ ВЫКЛЮЧАТЕЛЕМ: он может закрыть точку входа, но не может её
 * открыть. Иначе выключенный на сервере портал получал бы рабочие кнопки,
 * которые сервер всё равно отвергнет 403 — то есть обещание, за которым
 * ничего нет (ровно то, ради чего в featureFlags.ts написано «включать
 * вместе с экраном»).
 *
 * Права здесь тоже только ИНТЕРФЕЙСНЫЕ. Контракт, правило 1: выставлять и
 * отменять может админ портала или пользователь из списка «Бухгалтерия», и
 * проверка обязана быть на сервере. Скрытая кнопка — это забота о человеке
 * (он не тычет туда, где получит отказ), а не защита: запрос можно послать и
 * мимо интерфейса.
 *
 * Всё чистыми функциями и без Vue — node:test через tsx не резолвит .vue,
 * и логика, оставшаяся внутри компонента, ревью не проходит (тот же урок,
 * что дала форма «Создать проект», см. featureFlags.ts).
 */

import { PAID_FEATURE_BADGE, PAID_FEATURE_HINT } from './paidFeatures'
import { formatDaysRu } from './billingFormat'
import type { BillingFeatureState, PortalFeaturesPayload } from '~/types/billing'

/** Код функции в ответе /api/features и в модели PortalFeature. */
export const BILLING_FEATURE_CODE = 'billing'

/** Разобранное состояние одной функции портала. */
export type PortalFeatureInfo = {
  state: BillingFeatureState
  /** Дата окончания пробного периода в виде «ГГГГ-ММ-ДД» либо null. */
  trialUntil: string | null
}

/**
 * Чужое или отсутствующее значение state — это 'off'.
 *
 * Безопасное значение по умолчанию: на сервере функция по умолчанию выключена
 * (PortalFeature.state, default 'off'), и интерфейс, который при непонятном
 * ответе открывает платный экран, ошибается в сторону ложного обещания.
 */
export function normalizeFeatureState(raw: unknown): BillingFeatureState {
  const value = String(raw ?? '').trim().toLowerCase()

  return value === 'on' || value === 'trial' ? value : 'off'
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
    const trialRaw = String((payload as { trial_until?: unknown }).trial_until ?? '').trim()

    result[code] = {
      state: normalizeFeatureState((payload as { state?: unknown }).state),
      trialUntil: trialRaw ? trialRaw.slice(0, 10) : null,
    }
  }

  return result
}

/** Состояние одной функции. Не пришла — считаем выключенной. */
export function readPortalFeature(
  features: Record<string, PortalFeatureInfo> | null | undefined,
  code: string
): PortalFeatureInfo {
  return features?.[code] || { state: 'off', trialUntil: null }
}

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * Сколько полных дней осталось до конца пробного периода.
 *
 * Считаем в КАЛЕНДАРНЫХ днях, а не в часах: человеку важно «осталось 3 дня»,
 * а не «осталось 2,4 дня». Обе даты приводим к местной полуночи, поэтому
 * результат не скачет от времени суток. Сегодняшняя дата окончания — это 0
 * («последний день»), вчерашняя — отрицательное число («истёк»).
 *
 * null означает «срок не задан» (state = on или сервер не прислал дату).
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

/** Бейдж пробного периода. null — бейджа нет (срок не задан). */
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

export type BillingAccess = {
  /** Состояние с сервера. 'off' — в том числе когда сервер не ответил. */
  state: BillingFeatureState
  /** Экран открыт: пункт меню ведёт на мастер и реестр, а не на заглушку. */
  enabled: boolean
  /** Рисовать замок. */
  locked: boolean
  /** Дней до конца пробного периода либо null. */
  trialDaysLeft: number | null
  /** Текст бейджа рядом с пунктом меню и в шапке экрана. */
  badge: string | null
  /** Что делать человеку, если функция закрыта. */
  hint: string | null
  /** Ответ /api/features ещё не получен: состояние — предположение, не факт. */
  unknown: boolean
}

/**
 * Доступ к «Счёту и акту».
 *
 * Пока ответ сервера не получен (features = null), считаем функцию
 * ВЫКЛЮЧЕННОЙ, но помечаем unknown: экран в этот момент показывает загрузку,
 * а не заглушку «обратитесь к администратору». Мигание «замок -> экран» хуже,
 * чем полсекунды ожидания.
 *
 * Истёкший пробный период НЕ закрывает экран сам: сервер прислал state =
 * trial, значит он и решает, пускать ли (пишущие ручки всё равно закрыты
 * декоратором подписки). Интерфейс только честно пишет «пробный период
 * истёк», а отказ, если он придёт, показывается разобранным текстом.
 */
export function resolveBillingAccess(options: {
  features: Record<string, PortalFeatureInfo> | null | undefined
  flagEnabled: boolean
  now?: Date
}): BillingAccess {
  const unknown = !options.features
  const feature = readPortalFeature(options.features, BILLING_FEATURE_CODE)
  const daysLeft = feature.state === 'trial'
    ? trialDaysLeft(feature.trialUntil, options.now || new Date())
    : null

  const serverEnabled = feature.state === 'on' || feature.state === 'trial'
  const enabled = serverEnabled && options.flagEnabled

  let badge: string | null = null
  if (!enabled) {
    badge = PAID_FEATURE_BADGE
  } else if (feature.state === 'trial') {
    badge = trialBadgeText(daysLeft)
  }

  return {
    state: feature.state,
    enabled,
    locked: !enabled,
    trialDaysLeft: daysLeft,
    badge,
    hint: enabled ? null : PAID_FEATURE_HINT,
    unknown,
  }
}

/**
 * Список «Бухгалтерия» из настроек приложения.
 *
 * Идентификаторы приводим к строкам и чистим от пустых значений: в
 * конфигурации они могут прийти и числами (портал отдаёт id пользователя
 * по-разному в разных методах), а сравнение 11 === '11' молча вернёт false.
 */
export function normalizeAccountantIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []

  for (const value of raw) {
    const id = String(value ?? '').trim()
    if (!id || seen.has(id)) {
      continue
    }

    seen.add(id)
    result.push(id)
  }

  return result
}

/** Человек может выставлять и отменять: админ портала или «Бухгалтерия». */
export function isBillingManager(options: {
  isAdmin: boolean
  userId: string | number | null | undefined
  accountantIds: unknown
}): boolean {
  if (options.isAdmin) {
    return true
  }

  const userId = String(options.userId ?? '').trim()
  if (!userId) {
    return false
  }

  return normalizeAccountantIds(options.accountantIds).includes(userId)
}

export type BillingUiPermissions = {
  /** Реестр видят все: там нет ничего, чего человек не мог бы увидеть в CRM. */
  canViewRegistry: boolean
  canIssue: boolean
  canPrintAct: boolean
  canCancel: boolean
}

/**
 * Что показывать в интерфейсе.
 *
 * Отмена НЕ требует включённой подписки — контракт, правило 2: при state =
 * off создание и печать запрещены, а чтение реестра и отмена разрешены.
 * Портал, у которого подписка кончилась, обязан уметь отозвать свой же
 * ошибочный счёт.
 */
export function resolveBillingUiPermissions(
  access: Pick<BillingAccess, 'enabled'>,
  isManager: boolean
): BillingUiPermissions {
  return {
    canViewRegistry: true,
    canIssue: isManager && access.enabled,
    canPrintAct: isManager && access.enabled,
    canCancel: isManager,
  }
}
