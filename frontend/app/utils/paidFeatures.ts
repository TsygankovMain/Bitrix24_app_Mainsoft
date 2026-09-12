/**
 * Платные функции раздела «Финансы».
 *
 * Раздел появляется в меню ДО того, как функции написаны: это осознанно.
 * Пункт с замком отвечает на вопрос «умеет ли приложение считать деньги» —
 * человек видит, что умеет, но по подписке, и идёт к администратору, а не
 * ищет функцию в отчётах и не пишет в поддержку «у вас нет БДДС».
 *
 * Состояние функции сюда ПЕРЕДАЮТ аргументом — этот файл не решает, включено
 * ли что-нибудь, он только описывает функции и рисует их состояние.
 *
 * Откуда состояние берётся, у двух функций по-разному, и это важно:
 *  - БДДС: пока только фронтовый флаг FINANCE_BDDS_ENABLED. За замком не
 *    стоит ни одной ручки, охранять нечего, замок здесь — витрина;
 *  - Счёт и акт: состояние подписки портала с сервера (GET /api/features,
 *    см. app/utils/billingFeature.ts), а фронтовый флаг остался аварийным
 *    выключателем. Право доступа проверяет сервер (контракт, правила 1 и 2),
 *    интерфейс только не показывает кнопок, которые заведомо откажут.
 *
 * Идентификатор функции совпадает с параметром маршрута (/finance/<id>),
 * чтобы заглушка была одна на обе функции и ссылка читалась глазами.
 */

export type PaidFeatureId = 'bdds' | 'billing'

export type PaidFeature = {
  id: PaidFeatureId
  /** Подпись пункта меню и заголовок заглушки. */
  label: string
  /** Одна фраза о пользе — её видно и в меню, и на заглушке. */
  benefit: string
  /** Что функция делает, по пунктам. Без обещаний сроков. */
  details: string[]
}

/** Бейдж рядом с выключенным пунктом. Один на все платные функции. */
export const PAID_FEATURE_BADGE = 'по подписке'

/** Куда идти человеку. Сам он подписку включить не может — и не должен. */
export const PAID_FEATURE_HINT = 'Функция входит в платную подписку. Чтобы её подключили, обратитесь к администратору приложения.'

export const PAID_FEATURES: Record<PaidFeatureId, PaidFeature> = {
  bdds: {
    id: 'bdds',
    label: 'БДДС по проектам',
    benefit: 'Видеть, сколько денег проект принёс и сколько забрал, рядом с уже учтёнными часами.',
    details: [
      'Плановые и фактические поступления и платежи в разрезе проекта.',
      'Сверка с часами: где выработка есть, а денег нет.',
      'Остаток бюджета проекта без выгрузки в таблицу.',
    ],
  },
  billing: {
    id: 'billing',
    label: 'Счёт и акт',
    benefit: 'Выставлять счёт и готовить акт прямо из отражённых часов, без переноса цифр руками.',
    details: [
      'Счёт из отобранных часов проекта за период.',
      'Акт по тем же часам — суммы и перечень работ совпадают со счётом.',
      'Отметка о выставленном: один и тот же час не уходит в счёт дважды.',
    ],
  },
}

export type PaidFeatureState = {
  feature: PaidFeature
  /** Функция доступна. */
  enabled: boolean
  /** Рисовать замок и бейдж. */
  locked: boolean
  /** Текст бейджа либо null, если функция включена. */
  badge: string | null
  /** Подсказка «что делать» либо null, если функция включена. */
  hint: string | null
  /** Маршрут пункта меню. */
  to: string
}

export function isPaidFeatureId(value: unknown): value is PaidFeatureId {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(PAID_FEATURES, value)
}

/** Маршрут заглушки. Страница одна на обе функции, различает их параметром. */
export function paidFeatureRoute(id: PaidFeatureId): string {
  return `/finance/${id}`
}

/**
 * Состояние пункта меню по идентификатору функции и значению флага.
 *
 * Флаг передаётся аргументом, а не читается из featureFlags: так функция
 * остаётся чистой и проверяемой, а место, где решается «включено или нет»,
 * остаётся ровно одно — вызывающий компонент.
 */
export function resolvePaidFeatureState(id: PaidFeatureId, enabled: boolean): PaidFeatureState {
  const feature = PAID_FEATURES[id]

  return {
    feature,
    enabled,
    locked: !enabled,
    badge: enabled ? null : PAID_FEATURE_BADGE,
    hint: enabled ? null : PAID_FEATURE_HINT,
    to: paidFeatureRoute(id),
  }
}

/** Все платные функции разом — в порядке, в котором они стоят в меню. */
export function resolveFinanceFeatureStates(flags: {
  bddsEnabled: boolean
  billingEnabled: boolean
}): PaidFeatureState[] {
  return [
    resolvePaidFeatureState('bdds', flags.bddsEnabled),
    resolvePaidFeatureState('billing', flags.billingEnabled),
  ]
}
