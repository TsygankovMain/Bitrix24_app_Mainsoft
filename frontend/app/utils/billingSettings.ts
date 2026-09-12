/**
 * Настройки «Счёта и акта» внутри конфигурации приложения.
 *
 * Живут там же, где остальные серверные настройки — в /api/configuration
 * (AppConfigurationPayload, сохранение через POST /api/configuration/save),
 * а НЕ в app.option портала. Причина одна: все настройки нужны СЕРВЕРУ.
 * billing_allow_open_period решает, принимать ли выставление за незакрытый
 * месяц (контракт, правило 3), список «Бухгалтерия» — кому вообще разрешено
 * выставлять и отменять (правило 1, «проверка на сервере, не только в
 * интерфейсе»), наше юрлицо — от кого уходит счёт. Настройка, которую сервер
 * не видит, ничего не защищает и ничего не подставляет.
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
/**
 * Наше юрлицо, от которого выставляются ВСЕ счета.
 *
 * До этой настройки юрлицо счёта брали из карточки проекта
 * (ProjectCard.our_legal_entity_id), а карточки приходят с портала
 * синхронизацией: правка в базе приложения не живёт дольше следующего
 * обмена, и на боевом портале там оказались компании, своими юрлицами не
 * являющиеся. Поэтому настройка ПЕРЕКРЫВАЕТ карточку.
 *
 * Название хранится рядом с идентификатором только для показа: правда о
 * названии живёт на портале, и перед выставлением сервер перечитывает его
 * (billing_service.verify_our_company). Пустое название не делает настройку
 * незаданной — подпись просто деградирует до идентификатора.
 */
export const BILLING_OUR_COMPANY_ID_KEY = 'billing_our_company_id'
export const BILLING_OUR_COMPANY_NAME_KEY = 'billing_our_company_name'

export type BillingSettings = {
  /** Разрешить выставление за незакрытый месяц. */
  allowOpenPeriod: boolean
  /** Идентификаторы сотрудников из списка «Бухгалтерия». */
  accountantIds: string[]
  /** Наше юрлицо для выставления. Пусто — берётся из карточки проекта. */
  ourCompanyId: string
  /** Название нашего юрлица на момент выбора — только для показа. */
  ourCompanyName: string
}

/**
 * Строковое значение конфигурации.
 *
 * String(null) даёт 'null', String(undefined) — 'undefined', и такой
 * «идентификатор» выглядел бы как заданная настройка, уводя счёт к юрлицу,
 * которого нет. Ровно та же защита стоит на сервере
 * (ConfigurationService._normalize_text).
 */
function readText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }

  const text = String(value).trim()

  return ['none', 'null', 'undefined'].includes(text.toLowerCase()) ? '' : text
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

  const ourCompanyId = readText(config?.[BILLING_OUR_COMPANY_ID_KEY])

  return {
    allowOpenPeriod,
    accountantIds: normalizeAccountantIds(config?.[BILLING_ACCOUNTANT_IDS_KEY]),
    ourCompanyId,
    // Название без идентификатора бессмысленно: выставлять по одному названию
    // нельзя, а показывать «настройка задана» при пустом id — врать.
    ourCompanyName: ourCompanyId ? readText(config?.[BILLING_OUR_COMPANY_NAME_KEY]) : '',
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
    [BILLING_OUR_COMPANY_ID_KEY]: readText(settings.ourCompanyId),
    // Сохранять название при снятом юрлице нельзя: осиротевшее название
    // потом показалось бы как заданная настройка.
    [BILLING_OUR_COMPANY_NAME_KEY]: readText(settings.ourCompanyId)
      ? readText(settings.ourCompanyName)
      : '',
  }
}

/** Изменились ли настройки — кнопка «Сохранить» не должна гореть просто так. */
export function billingSettingsChanged(left: BillingSettings, right: BillingSettings): boolean {
  if (Boolean(left.allowOpenPeriod) !== Boolean(right.allowOpenPeriod)) {
    return true
  }

  // Сравниваем только идентификатор: название приезжает с портала и может
  // отличаться регистром или пробелами, а кнопка «Сохранить» не должна
  // гореть из-за того, что справочник загрузился.
  if (readText(left.ourCompanyId) !== readText(right.ourCompanyId)) {
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
