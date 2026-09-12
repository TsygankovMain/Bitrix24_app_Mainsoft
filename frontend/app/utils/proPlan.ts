/**
 * Тариф Pro: название, цена и куда вести человека за подключением.
 *
 * Тариф один на портал и открывает все платные функции (БДДС, счёт и акт,
 * ролевую модель) — backends/python/api/main/billing_features.py,
 * PLAN_FEATURES. Биллинг по порталу, цена по умолчанию 3000 ₽ в месяц; если
 * сервер прислал другую цену (price_month_rub в /api/features), показываем её.
 *
 * Все кнопки «Купить Pro» ведут на /pro (app/pages/pro.client.vue) — форму
 * запроса счёта. Её модель, проверки и тексты состояний —
 * app/utils/proPurchase.ts.
 *
 * Всё чистыми функциями и без Vue: node:test через tsx не резолвит .vue.
 */

export const PRO_PLAN_CODE = 'pro'
export const PRO_PLAN_LABEL = 'Pro'
export const PRO_PRICE_MONTH_RUB = 3000

/** Маршрут формы запроса счёта на Pro. */
export const PRO_ROUTE = '/pro'
export const PRO_CTA_LABEL = 'Купить Pro'
export const PRO_CONTACT_EMAIL = 'timesheet@mainsoft.su'

const NBSP = '\u00A0'

/** «3000 ₽ в месяц за портал». Негодная цена — цена по умолчанию. */
export function proPriceText(price: unknown = PRO_PRICE_MONTH_RUB): string {
  const value = Number(price)
  const amount = Number.isFinite(value) && value > 0 ? Math.round(value) : PRO_PRICE_MONTH_RUB

  return `${amount}${NBSP}₽ в месяц за портал`
}

/**
 * Адрес «Купить Pro» с функцией, с которой человек пришёл: форма подсвечивает
 * её в списке того, что входит в Pro, и возвращает назад. Незнакомый код не
 * передаём.
 */
export function proRoute(featureId?: string | null): string {
  const id = String(featureId || '').trim()

  return /^[a-z_]+$/.test(id) ? `${PRO_ROUTE}?feature=${id}` : PRO_ROUTE
}

/** «2026-10-31» -> «31.10.2026». Пусто и мусор — пустая строка. */
export function formatPlanDate(value: string | null | undefined): string {
  const match = String(value || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})/)

  return match ? `${match[3]}.${match[2]}.${match[1]}` : ''
}

/** Следующий день после даты «ГГГГ-ММ-ДД» в том же виде; мусор — null. */
export function nextPlanDay(value: string | null | undefined): string | null {
  const match = String(value || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) {
    return null
  }

  const next = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + 1))

  return next.toISOString().slice(0, 10)
}
