/**
 * Настройки «БДДС по проектам» внутри конфигурации приложения.
 *
 * Живут там же, где остальные серверные настройки — в /api/configuration
 * (сохранение через POST /api/configuration/save), а НЕ в личных настройках
 * и не отдельным механизмом. Причина та же, что у «Счёта и акта»: все эти
 * значения нужны СЕРВЕРУ. Пороги решают, какой статус получит проект и
 * уйдёт ли уведомление; выключатель гасит рассылку; список адресатов —
 * кому она уходит кроме куратора. Настройка, которую сервер не видит,
 * ничего не меняет.
 *
 * Ключи (bdds_*) читает бэкенд — main/bdds_settings.py::CONFIG_KEYS.
 * Опечатка в одном из двух мест проявится только в бою, поэтому они здесь
 * константами и покрыты тестами.
 *
 * Выключатель ПОДПИСКИ сюда не кладётся принципиально: он на нашем сервере
 * (модель PortalSubscription), потому что app.option портала пишется токеном
 * приложения, то есть из консоли браузера.
 */

import type { AppConfigurationPayload } from '~/types/config'

export const BDDS_NOTIFICATIONS_ENABLED_KEY = 'bdds_notifications_enabled'
export const BDDS_RISK_THRESHOLD_KEY = 'bdds_risk_threshold_percent'
export const BDDS_OVERRUN_THRESHOLD_KEY = 'bdds_overrun_threshold_percent'
export const BDDS_NOTIFY_USER_IDS_KEY = 'bdds_notify_user_ids'

export const BDDS_DEFAULT_RISK_PERCENT = 80
export const BDDS_DEFAULT_OVERRUN_PERCENT = 100

export type BddsSettings = {
  /** Рассылать ли уведомления о риске и перерасходе. */
  notificationsEnabled: boolean
  /** Порог «Риск», процент освоения. */
  riskPercent: number
  /** Порог «Перерасход», процент освоения. */
  overrunPercent: number
  /** Кому уведомление уходит кроме куратора проекта («финансы»). */
  notifyUserIds: string[]
}

export function defaultBddsSettings(): BddsSettings {
  return {
    notificationsEnabled: true,
    riskPercent: BDDS_DEFAULT_RISK_PERCENT,
    overrunPercent: BDDS_DEFAULT_OVERRUN_PERCENT,
    notifyUserIds: [],
  }
}

/**
 * Булево значение конфигурации.
 *
 * app.option портала возвращает всё строками, и Boolean('false') истинно —
 * поэтому разбор свой, как и на сервере. Отсутствие ключа (настройку ещё
 * не сохраняли) означает «включено»: уведомления — смысл функции, а не
 * дополнение к ней.
 */
function readFlag(value: unknown, fallback: boolean): boolean {
  if (value === undefined || value === null || value === '') {
    return fallback
  }
  if (typeof value === 'boolean') {
    return value
  }

  const text = String(value).trim().toLowerCase()
  if (['1', 'true', 'yes', 'y', 'on'].includes(text)) {
    return true
  }
  if (['0', 'false', 'no', 'n', 'off'].includes(text)) {
    return false
  }

  return fallback
}

/** Процент больше нуля либо значение по умолчанию. Мусор порогом не становится. */
function readPercent(value: unknown, fallback: number): number {
  const text = typeof value === 'string' ? value.trim().replace(',', '.') : value
  const parsed = Number(text)

  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback
  }

  return Math.round(parsed * 100) / 100
}

/** Идентификаторы сотрудников: строками, без пустых, 'None' и дублей. */
export function normalizeBddsUserIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const seen = new Set<string>()
  const result: string[] = []

  for (const value of raw) {
    const id = String(value ?? '').trim()
    if (!id || seen.has(id) || ['none', 'null', 'undefined'].includes(id.toLowerCase())) {
      continue
    }

    seen.add(id)
    result.push(id)
  }

  return result
}

export function readBddsSettings(config: AppConfigurationPayload | null | undefined): BddsSettings {
  const source = config || {}
  const defaults = defaultBddsSettings()

  const overrun = readPercent(source[BDDS_OVERRUN_THRESHOLD_KEY], defaults.overrunPercent)
  const risk = readPercent(source[BDDS_RISK_THRESHOLD_KEY], defaults.riskPercent)

  return {
    notificationsEnabled: readFlag(
      source[BDDS_NOTIFICATIONS_ENABLED_KEY],
      defaults.notificationsEnabled
    ),
    // Перепутанные местами пороги чиним так же, как сервер: иначе зона
    // «Риск» стала бы недостижимой, и человек увидел бы это не в настройке,
    // а в отчёте.
    riskPercent: Math.min(risk, overrun),
    overrunPercent: Math.max(risk, overrun),
    notifyUserIds: normalizeBddsUserIds(source[BDDS_NOTIFY_USER_IDS_KEY]),
  }
}

/**
 * Свои ключи поверх конфигурации ЦЕЛИКОМ.
 *
 * /api/configuration/save принимает объект целиком, и отправка одних только
 * своих ключей затёрла бы сопоставление полей смарт-процессов — то есть всю
 * настройку приложения.
 */
export function applyBddsSettings(
  config: AppConfigurationPayload | null | undefined,
  settings: BddsSettings
): AppConfigurationPayload {
  const risk = readPercent(settings.riskPercent, BDDS_DEFAULT_RISK_PERCENT)
  const overrun = readPercent(settings.overrunPercent, BDDS_DEFAULT_OVERRUN_PERCENT)

  return {
    ...(config || {}),
    [BDDS_NOTIFICATIONS_ENABLED_KEY]: Boolean(settings.notificationsEnabled),
    [BDDS_RISK_THRESHOLD_KEY]: Math.min(risk, overrun),
    [BDDS_OVERRUN_THRESHOLD_KEY]: Math.max(risk, overrun),
    [BDDS_NOTIFY_USER_IDS_KEY]: normalizeBddsUserIds(settings.notifyUserIds),
  }
}

/** Изменились ли настройки — кнопка «Сохранить» не должна гореть просто так. */
export function bddsSettingsChanged(left: BddsSettings, right: BddsSettings): boolean {
  if (Boolean(left.notificationsEnabled) !== Boolean(right.notificationsEnabled)) {
    return true
  }
  if (Number(left.riskPercent) !== Number(right.riskPercent)) {
    return true
  }
  if (Number(left.overrunPercent) !== Number(right.overrunPercent)) {
    return true
  }

  const leftIds = normalizeBddsUserIds(left.notifyUserIds)
  const rightIds = normalizeBddsUserIds(right.notifyUserIds)

  return leftIds.length !== rightIds.length
    || leftIds.some((id, index) => id !== rightIds[index])
}

/**
 * Что настройка обещает человеку — одной строкой под полями.
 *
 * Текст объясняет, что пороги применяются и к статусу, и к уведомлениям:
 * иначе «порог риска» читается как настройка только рассылки, и человек
 * удивляется поменявшимся цветам в реестре.
 */
export function describeBddsThresholds(settings: BddsSettings): string {
  return `Статус «Риск» — с ${settings.riskPercent}% освоения, «Перерасход» — выше ${settings.overrunPercent}%.`
    + ' Те же пороги решают, когда уходит уведомление.'
}
