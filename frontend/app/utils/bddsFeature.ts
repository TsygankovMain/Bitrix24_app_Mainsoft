/**
 * Подписка на «БДДС по проектам» в интерфейсе.
 *
 * Состояние приходит с сервера тем же контрактом, что и у «Счёта и акта»:
 * GET /api/features отдаёт {"bdds": {"state": "on"|"trial"|"off", ...}}.
 * ВТОРОГО механизма подписки в приложении нет и быть не должно — этот файл
 * только читает готовый разбор из billingFeature.ts (parsePortalFeatures,
 * readPortalFeature, trialDaysLeft, trialBadgeText) и добавляет к нему
 * аварийный выключатель БДДС.
 *
 * Почему отдельный файл, а не ветка в billingFeature.ts. Там всё про счёт:
 * права «Бухгалтерии», отмена документа при выключенной подписке,
 * разрешения кнопок мастера. У БДДС из этого нет ничего: нет документа,
 * нет прав по ролям, и подписка закрывает в том числе ЧТЕНИЕ (см.
 * feature_required в backends/python/api/main/billing_features.py).
 * Дописывать это в файл счёта — смешивать две функции в одном месте.
 *
 * Всё чистыми функциями и без Vue: node:test через tsx не резолвит .vue, и
 * логика, оставшаяся внутри компонента, ревью не проходит.
 */

import { PAID_FEATURE_BADGE, PAID_FEATURE_HINT } from './paidFeatures'
import { readPortalFeature, trialBadgeText, trialDaysLeft, type PortalFeatureInfo } from './billingFeature'
import type { BillingFeatureState } from '~/types/billing'

/** Код функции в ответе /api/features и в модели PortalFeature. */
export const BDDS_FEATURE_CODE = 'bdds'

export type BddsAccess = {
  /** Состояние с сервера. 'off' — в том числе когда сервер не ответил. */
  state: BillingFeatureState
  /** Экран открыт: пункт меню ведёт на реестр, а не на заглушку. */
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
 * Доступ к «БДДС по проектам».
 *
 * Пока ответ сервера не получен (features = null), функция считается
 * ВЫКЛЮЧЕННОЙ, но помечается unknown: экран в этот момент показывает
 * «Проверяем подписку…», а не заглушку «обратитесь к администратору».
 * Мигание «замок -> экран» лучше обратного — пункта без замка, ведущего на
 * отказ сервера.
 *
 * Фронтовый флаг остаётся АВАРИЙНЫМ ВЫКЛЮЧАТЕЛЕМ: он может закрыть точку
 * входа на всех порталах разом, но не может открыть её вопреки серверу.
 */
export function resolveBddsAccess(options: {
  features: Record<string, PortalFeatureInfo> | null | undefined
  flagEnabled: boolean
  now?: Date
}): BddsAccess {
  const unknown = !options.features
  const feature = readPortalFeature(options.features, BDDS_FEATURE_CODE)
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
