/**
 * Настройки «Счёта и акта» внутри конфигурации приложения.
 *
 * Живут там же, где остальные серверные настройки — в /api/configuration
 * (AppConfigurationPayload, сохранение через POST /api/configuration/save),
 * а НЕ в app.option портала. Причина одна: обе настройки нужны СЕРВЕРУ.
 * billing_allow_open_period решает, принимать ли выставление за незакрытый
 * месяц (контракт, правило 3), список «Бухгалтерия» — кому вообще разрешено
 * выставлять и отменять (правило 1, «проверка на сервере, не только в
 * интерфейсе»). Настройка, которую сервер не видит, ничего не защищает.
 *
 * Ключи держим строками-константами в одном месте: их читает и бэкенд, и
 * опечатка в одном из двух мест проявится только в бою.
 */

import { normalizeAccountantIds } from './billingFeature'
import type { AppConfigurationPayload } from '~/types/config'

export const BILLING_ALLOW_OPEN_PERIOD_KEY = 'billing_allow_open_period'
/**
 * Ключ списка «Бухгалтерия» в конфигурации.
 *
 * Имя выбрано НЕ нами: его читает сервер (billing_settings.py::
 * load_billing_settings), и переименование здесь молча лишило бы всех
 * бухгалтеров прав — сервер продолжил бы искать свой ключ и находить пустой
 * список. Третий ключ функции, billing_act_template_id (заранее выбранный
 * шаблон акта), этим экраном не управляется: его задаёт портал.
 */
export const BILLING_ACCOUNTANT_IDS_KEY = 'billing_accountants'

export type BillingSettings = {
  /** Разрешить выставление за незакрытый месяц. */
  allowOpenPeriod: boolean
  /** Идентификаторы сотрудников из списка «Бухгалтерия». */
  accountantIds: string[]
}

/**
 * Настройки из конфигурации.
 *
 * Отсутствие ключа — это «запрещено» и «список пуст», то есть самое строгое
 * из возможных состояний: выставлять можно только за закрытый месяц и только
 * админу портала. Ошибаться в сторону разрешения здесь нельзя.
 *
 * Булево значение приходит и строкой: конфигурация переживала несколько
 * версий сохранения, и '1'/'true' в ней встречаются наравне с true.
 */
export function readBillingSettings(config: AppConfigurationPayload | null | undefined): BillingSettings {
  const raw = config?.[BILLING_ALLOW_OPEN_PERIOD_KEY]
  const allowOpenPeriod = raw === true
    || raw === 1
    || (typeof raw === 'string' && ['1', 'true', 'yes', 'on'].includes(raw.trim().toLowerCase()))

  return {
    allowOpenPeriod,
    accountantIds: normalizeAccountantIds(config?.[BILLING_ACCOUNTANT_IDS_KEY]),
  }
}

/**
 * Конфигурация с новыми настройками «Счёта и акта».
 *
 * Возвращает КОПИЮ и сохраняет все прочие ключи: /api/configuration/save
 * принимает конфигурацию целиком, и сохранение частичного объекта затёрло бы
 * сопоставление полей смарт-процессов — то есть всю настройку приложения.
 */
export function applyBillingSettings(
  config: AppConfigurationPayload | null | undefined,
  settings: BillingSettings
): AppConfigurationPayload {
  return {
    ...(config || {}),
    [BILLING_ALLOW_OPEN_PERIOD_KEY]: Boolean(settings.allowOpenPeriod),
    [BILLING_ACCOUNTANT_IDS_KEY]: normalizeAccountantIds(settings.accountantIds),
  }
}

/** Изменились ли настройки — кнопка «Сохранить» не должна гореть просто так. */
export function billingSettingsChanged(left: BillingSettings, right: BillingSettings): boolean {
  if (Boolean(left.allowOpenPeriod) !== Boolean(right.allowOpenPeriod)) {
    return true
  }

  const a = normalizeAccountantIds(left.accountantIds)
  const b = normalizeAccountantIds(right.accountantIds)

  if (a.length !== b.length) {
    return true
  }

  const sortedA = [...a].sort()
  const sortedB = [...b].sort()

  return sortedA.some((value, index) => value !== sortedB[index])
}
