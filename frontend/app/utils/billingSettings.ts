/**
 * Настройки «Счёта и акта» внутри конфигурации приложения.
 *
 * Живут там же, где остальные серверные настройки — в /api/configuration
 * (AppConfigurationPayload, сохранение через POST /api/configuration/save),
 * а НЕ в app.option портала. Причина одна: все настройки нужны СЕРВЕРУ.
 * billing_allow_open_period решает, принимать ли выставление за незакрытый
 * месяц (контракт, правило 3), список «Бухгалтерия» — кому вообще разрешено
 * выставлять и отменять (правило 1, «проверка на сервере, не только в
 * интерфейсе»), наше юрлицо — от кого уходит счёт, шаблоны генератора
 * документов — чем печатать. Настройка, которую сервер
 * не видит, ничего не защищает и ничего не подставляет.
 *
 * Ключи держим строками-константами в одном месте: их читает и бэкенд, и
 * опечатка в одном из двух мест проявится только в бою.
 */

import { normalizeAccountantIds } from './billingFeature'
import {
  BILLING_LINE_TASK_LEVEL_KEY,
  BILLING_LINE_VARIANT_KEY,
  BILLING_LINE_VARIANTS,
  BILLING_SERVICE_NAME_KEY,
  normalizeBillingLineTemplate,
  normalizeBillingLineVariant,
  normalizeBillingServiceName,
  normalizeBillingTaskLevel,
} from './billingLineTemplate'
import type { BillingLineVariant, BillingTaskLevel } from './billingLineTemplate'
import type { AppConfigurationPayload } from '~/types/config'

export const BILLING_ALLOW_OPEN_PERIOD_KEY = 'billing_allow_open_period'
/**
 * Ключ списка «Бухгалтерия» в конфигурации.
 *
 * Имя выбрано НЕ нами: его читает сервер (billing_settings.py::
 * load_billing_settings), и переименование здесь молча лишило бы всех
 * бухгалтеров прав — сервер продолжил бы искать свой ключ и находить пустой
 * список.
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
/**
 * Шаблоны генератора документов портала: акт и печатная форма счёта.
 *
 * До этой настройки billing_act_template_id задавался только числом прямо в
 * конфигурации — идентификатор шаблона приходилось узнавать запросом к
 * порталу руками, а при пустой настройке приложение печатало акт первым
 * шаблоном, в названии которого есть «акт».
 *
 * Два ключа, а не один, потому что это два РАЗНЫХ документа: у акта и у
 * счёта свои шаблоны (на портале — ACT_RU и BILL_RU), свои нумераторы и свои
 * отказы. Один ключ заставил бы печатать обе половины комплекта одним
 * шаблоном, то есть отправить клиенту два одинаковых документа.
 *
 * Ноль — «не выбран», и это рабочее состояние: для счёта печать просто
 * недоступна (угадывать нельзя — под «счёт» на портале подходят и
 * счёт-фактура, и УПД), для акта остаётся прежний подбор по названию.
 */
export const BILLING_ACT_TEMPLATE_ID_KEY = 'billing_act_template_id'
export const BILLING_INVOICE_TEMPLATE_ID_KEY = 'billing_invoice_template_id'

export {
  BILLING_LINE_TASK_LEVEL_KEY,
  BILLING_LINE_TEMPLATE_KEY,
  BILLING_LINE_VARIANT_KEY,
  BILLING_SERVICE_NAME_KEY,
} from './billingLineTemplate'

export type BillingSettings = {
  /** Разрешить выставление за незакрытый месяц. */
  allowOpenPeriod: boolean
  /** Идентификаторы сотрудников из списка «Бухгалтерия». */
  accountantIds: string[]
  /** Наше юрлицо для выставления. Пусто — берётся из карточки проекта. */
  ourCompanyId: string
  /** Название нашего юрлица на момент выбора — только для показа. */
  ourCompanyName: string
  /**
   * Вариант наполнения счёта, который мастер подставляет при открытии.
   *
   * Раньше «по задачам» было зашито в код, и портал, выставляющий одной
   * строкой, переключал вариант в каждом счёте руками.
   */
  lineVariant: BillingLineVariant
  /**
   * Формулировка строки — СВОЯ У КАЖДОГО варианта. Текст строк собирает
   * сервер, эти настройки — его правила.
   */
  lineTemplates: Record<BillingLineVariant, string>
  /** Текст услуги для подстановки `{услуга}` («Разработка»). */
  serviceName: string
  /**
   * Уровень задачи в строке: сама задача («task») или её родитель верхнего
   * уровня («root»). Влияет только на группировку по задачам.
   */
  taskLevel: BillingTaskLevel
  /** Шаблон акта в генераторе документов портала; '' — не выбран. */
  actTemplateId: string
  /** Шаблон печатной формы счёта; '' — печать счёта недоступна. */
  invoiceTemplateId: string
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
 * Идентификатор шаблона: строкой, но нормализованный.
 *
 * Сервер хранит его числом, а <select> отдаёт строку — без нормализации
 * '4' и 4 были бы двумя состояниями одной настройки, и кнопка «Сохранить»
 * загоралась бы сразу после загрузки страницы. Ноль, отрицательные и мусор
 * читаются как «не выбран»: сохранённый id 0 иначе выглядел бы как
 * выбранный шаблон.
 */
export function readTemplateId(value: unknown): string {
  const text = readText(value)

  if (!/^[0-9]+$/.test(text)) {
    return ''
  }

  const numeric = Number(text)

  return Number.isFinite(numeric) && numeric > 0 ? String(numeric) : ''
}

/**
 * Формулировки всех вариантов из конфигурации.
 *
 * Ключ варианта «по задачам» — прежний `billing_line_template` без суффикса:
 * под ним формулировка уже лежит в конфигурации порталов, и новый ключ
 * молча вернул бы им текст по умолчанию.
 */
export function readBillingLineTemplates(
  config: AppConfigurationPayload | null | undefined
): Record<BillingLineVariant, string> {
  const result = {} as Record<BillingLineVariant, string>

  for (const variant of BILLING_LINE_VARIANTS) {
    result[variant.id] = normalizeBillingLineTemplate(config?.[variant.settingKey], variant.id)
  }

  return result
}

/** Формулировки всех вариантов -> ключи конфигурации. */
export function applyBillingLineTemplates(
  templates: Record<string, string> | null | undefined
): AppConfigurationPayload {
  const result: AppConfigurationPayload = {}

  for (const variant of BILLING_LINE_VARIANTS) {
    result[variant.settingKey] = normalizeBillingLineTemplate(
      templates?.[variant.id], variant.id,
    )
  }

  return result
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
    lineVariant: normalizeBillingLineVariant(config?.[BILLING_LINE_VARIANT_KEY]),
    // Пустой шаблон читается как «как по умолчанию ЭТОГО варианта»: иначе
    // строка счёта осталась бы без наименования работ, а формулировка
    // варианта «по задачам» в счёте на одну строку прочиталась бы как
    // «Услуги по договору, август 2026».
    lineTemplates: readBillingLineTemplates(config),
    serviceName: normalizeBillingServiceName(config?.[BILLING_SERVICE_NAME_KEY]),
    taskLevel: normalizeBillingTaskLevel(config?.[BILLING_LINE_TASK_LEVEL_KEY]),
    actTemplateId: readTemplateId(config?.[BILLING_ACT_TEMPLATE_ID_KEY]),
    invoiceTemplateId: readTemplateId(config?.[BILLING_INVOICE_TEMPLATE_ID_KEY]),
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
    [BILLING_LINE_VARIANT_KEY]: normalizeBillingLineVariant(settings.lineVariant),
    ...applyBillingLineTemplates(settings.lineTemplates),
    [BILLING_SERVICE_NAME_KEY]: normalizeBillingServiceName(settings.serviceName),
    [BILLING_LINE_TASK_LEVEL_KEY]: normalizeBillingTaskLevel(settings.taskLevel),
    // Числом, как это хранит сервер: строка из <select> и число из ответа
    // сервера иначе стали бы двумя формами одного значения, и живая проверка
    // шаблона на портале срабатывала бы на каждом сохранении настроек.
    [BILLING_ACT_TEMPLATE_ID_KEY]: Number(readTemplateId(settings.actTemplateId) || 0),
    [BILLING_INVOICE_TEMPLATE_ID_KEY]: Number(readTemplateId(settings.invoiceTemplateId) || 0),
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

  if (normalizeBillingLineVariant(left.lineVariant) !== normalizeBillingLineVariant(right.lineVariant)) {
    return true
  }

  if (normalizeBillingServiceName(left.serviceName) !== normalizeBillingServiceName(right.serviceName)) {
    return true
  }

  // Шаблоны сравниваем нормализованными, каждый со своим вариантом: пустое
  // поле и значение по умолчанию — одно и то же состояние, и кнопка
  // «Сохранить» не должна гореть из-за стёртого пробела.
  const changedWording = BILLING_LINE_VARIANTS.some(
    variant => normalizeBillingLineTemplate(left.lineTemplates?.[variant.id], variant.id)
      !== normalizeBillingLineTemplate(right.lineTemplates?.[variant.id], variant.id)
  )

  if (changedWording) {
    return true
  }

  if (normalizeBillingTaskLevel(left.taskLevel) !== normalizeBillingTaskLevel(right.taskLevel)) {
    return true
  }

  // Шаблоны сравниваем нормализованными: '', '0' и 0 — одно состояние
  // «не выбран», и загрузка списка шаблонов не должна зажигать «Сохранить».
  if (readTemplateId(left.actTemplateId) !== readTemplateId(right.actTemplateId)) {
    return true
  }

  if (readTemplateId(left.invoiceTemplateId) !== readTemplateId(right.invoiceTemplateId)) {
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
