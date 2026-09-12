/**
 * Подписка на «Счёт и акт» и права в интерфейсе.
 *
 * Состояние функции приходит с сервера: GET /api/features, разбор общий для
 * всех платных функций — app/utils/featureAccess.ts (тариф Pro, «только
 * чтение» после окончания). Фронтовый флаг FINANCE_BILLING_ENABLED остаётся
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

import {
  resolveFeatureAccess,
  type FeatureAccess,
} from './featureAccess'

// Разбор ответа /api/features (parsePortalFeatures, readPortalFeature,
// trialDaysLeft, trialBadgeText) переехал в featureAccess.ts — он общий для
// всех платных функций. Реэкспорта нет намеренно: Nuxt автоимпортирует utils,
// и одно имя из двух файлов даёт предупреждение «Duplicated imports».

/** Код функции в ответе /api/features. */
export const BILLING_FEATURE_CODE = 'billing'

export type BillingAccess = FeatureAccess

/**
 * Доступ к «Счёту и акту».
 *
 * Пока ответ сервера не получен (features = null), функция считается
 * закрытой, но помечена unknown: экран показывает загрузку, а не заглушку.
 *
 * enabled — экран открыт (в том числе «только чтение» после окончания Pro:
 * реестр и карточки видны). canWrite — можно выставлять и печатать.
 */
export function resolveBillingAccess(options: {
  features: Parameters<typeof resolveFeatureAccess>[0]['features']
  flagEnabled: boolean
  now?: Date
}): BillingAccess {
  return resolveFeatureAccess({
    features: options.features,
    code: BILLING_FEATURE_CODE,
    title: 'Счёт и акт',
    flagEnabled: options.flagEnabled,
    now: options.now,
  })
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
 * Выставление и печать — только при действующем Pro (canWrite). Отмена НЕ
 * требует тарифа — контракт, правило 2: портал, у которого Pro закончился,
 * обязан уметь отозвать свой же ошибочный счёт. Старый вызов с одним
 * enabled (без canWrite) трактуется как прежде.
 */
export function resolveBillingUiPermissions(
  access: Pick<BillingAccess, 'enabled'> & Partial<Pick<BillingAccess, 'canWrite'>>,
  isManager: boolean
): BillingUiPermissions {
  const canWrite = access.canWrite ?? access.enabled

  return {
    canViewRegistry: true,
    canIssue: isManager && access.enabled && canWrite,
    canPrintAct: isManager && access.enabled && canWrite,
    canCancel: isManager,
  }
}
