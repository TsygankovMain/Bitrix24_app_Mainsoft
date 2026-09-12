/**
 * Подписка на «БДДС по проектам» в интерфейсе.
 *
 * Состояние приходит с сервера тем же ответом, что у всех платных функций:
 * GET /api/features. ВТОРОГО механизма подписки в приложении нет — разбор и
 * правило общие (app/utils/featureAccess.ts), здесь только код функции,
 * её название и аварийный выключатель.
 *
 * Правило сервера для БДДС: без тарифа Pro закрыто всё, включая чтение;
 * после окончания Pro — «только чтение»: реестр и бюджеты видны, добавить
 * операцию и прогнать уведомления нельзя (@feature_required('bdds')).
 */

import { resolveFeatureAccess, type FeatureAccess, type PortalFeatureInfo } from './featureAccess'

/** Код функции в ответе /api/features. */
export const BDDS_FEATURE_CODE = 'bdds'

export type BddsAccess = FeatureAccess

/**
 * Доступ к «БДДС по проектам».
 *
 * Пока ответ сервера не получен (features = null), функция считается
 * закрытой, но помечается unknown: экран показывает «Проверяем подписку…».
 * Фронтовый флаг — АВАРИЙНЫЙ ВЫКЛЮЧАТЕЛЬ: закрыть может, открыть — нет.
 */
export function resolveBddsAccess(options: {
  features: Record<string, PortalFeatureInfo> | null | undefined
  flagEnabled: boolean
  now?: Date
}): BddsAccess {
  return resolveFeatureAccess({
    features: options.features,
    code: BDDS_FEATURE_CODE,
    title: 'БДДС по проектам',
    flagEnabled: options.flagEnabled,
    now: options.now,
  })
}
