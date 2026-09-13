/**
 * Платные функции: «Финансы» (БДДС, счёт и акт) и ролевая модель.
 *
 * Все они входят в один тариф Pro портала (app/utils/proPlan.ts). Пункт с
 * замком отвечает на вопрос «умеет ли приложение считать деньги» — человек
 * видит, что умеет, но в Pro, и жмёт «Подключить Pro», а не ищет функцию в
 * отчётах и не пишет в поддержку «у вас нет БДДС».
 *
 * Состояние функции сюда ПЕРЕДАЮТ аргументом — этот файл не решает, включено
 * ли что-нибудь, он только описывает функции и рисует их состояние.
 *
 * Откуда состояние берётся — у обеих функций ОДИНАКОВО: подписка портала с
 * сервера (GET /api/features, один ответ на все платные функции), а
 * фронтовые флаги FINANCE_* остались аварийными выключателями. Разбор
 * ответа — app/utils/billingFeature.ts (счёт) и app/utils/bddsFeature.ts
 * (БДДС). Право доступа проверяет сервер, интерфейс только не показывает
 * кнопок, которые заведомо откажут.
 *
 * Правило сервера одно для всех (billing_features): без тарифа функция
 * закрыта, после окончания тарифа — «только чтение»: создание и изменение
 * закрыты, просмотр и выгрузки работают. У счёта реестр и отмена открыты
 * даже без тарифа — клиента нельзя лишать выставленных документов.
 *
 * Идентификатор функции совпадает с параметром маршрута (/finance/<id>),
 * чтобы заглушка была одна на обе функции и ссылка читалась глазами.
 */

import { PRO_PLAN_LABEL, proPriceText, proRoute } from './proPlan'

export type PaidFeatureId = 'bdds' | 'billing' | 'roles'

/** Функции раздела «Финансы» — у них общая заглушка /finance/<id>. */
export type FinanceFeatureId = Exclude<PaidFeatureId, 'roles'>

export type PaidFeature = {
  id: PaidFeatureId
  /** Подпись пункта меню и заголовок заглушки. */
  label: string
  /** Одна фраза о пользе — её видно и в меню, и на заглушке. */
  benefit: string
  /** Что функция делает, по пунктам. Без обещаний сроков. */
  details: string[]
}

/**
 * Бейдж рядом с закрытым пунктом. Один на все платные функции: все они
 * входят в один тариф Pro (app/utils/proPlan.ts), и бейдж называет тариф, а
 * не абстрактную «подписку» — человеку понятно, что именно подключать.
 */
export const PAID_FEATURE_BADGE = PRO_PLAN_LABEL

/** Короткая подсказка у закрытой функции: тариф и цена. Кнопка — отдельно. */
export const PAID_FEATURE_HINT = `Входит в тариф ${PRO_PLAN_LABEL} — ${proPriceText()}.`

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
  roles: {
    id: 'roles',
    label: 'Ролевая модель',
    benefit: 'Разграничить, кто видит деньги и кто может выставлять, закрывать и править, — без выдачи прав администратора.',
    details: [
      'Роли сотрудников: кто вносит часы, кто ведёт финансы, кто только смотрит.',
      'Суммы и ставки видят только те, кому они нужны для работы.',
      'Права проверяет сервер, а не скрытые кнопки.',
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

/** Функция раздела «Финансы»: у ролевой модели свой раздел, не /finance/roles. */
export function isFinanceFeatureId(value: unknown): value is FinanceFeatureId {
  return isPaidFeatureId(value) && value !== 'roles'
}

/** Маршрут заглушки. Страница одна на функции «Финансов», различает их параметром. */
export function paidFeatureRoute(id: FinanceFeatureId): string {
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
    to: isFinanceFeatureId(id) ? paidFeatureRoute(id) : proRoute(id),
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
