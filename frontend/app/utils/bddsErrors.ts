/**
 * Отказы БДДС человеческим текстом.
 *
 * Разбор самой ошибки (статус, код, тело) НЕ дублируется: читаем готовые
 * readErrorStatus / readErrorCode / readErrorPayload из billingErrors.ts —
 * это общий разбор ответа ofetch, а не логика счёта. Отдельные здесь только
 * ТЕКСТЫ: у БДДС свои коды (feature_disabled, finance_spa_not_configured,
 * project_not_found), и подсказки к ним ведут в другие места приложения.
 *
 * Почему отказ показывается плашкой, а не фатальным экраном: экран БДДС
 * живёт рядом с часами и отчётами, и недоступная ручка денег не должна
 * ронять приложение целиком (тот же принцип, что у «Счёта и акта»).
 */

import { readErrorCode, readErrorPayload, readErrorStatus } from './billingErrors'
import { isRateLimitError, RATE_LIMIT_NOTICE_TEXT } from './apiErrors'

export type BddsErrorView = {
  title: string
  /** Что делать человеку. Пустая строка — подсказки нет. */
  hint: string
  /** Отказ по подписке: экран показывает заглушку с замком, а не плашку. */
  isFeatureDisabled: boolean
  /** Проект не найден: адрес открыт с чужим или устаревшим id. */
  isProjectMissing: boolean
  /**
   * Смарт-процесс операций не настроен (код finance_spa_not_configured).
   *
   * Отдельный признак, а не разбор текста на экране: это не ошибка и не
   * «операций нет», а незаполненная настройка приложения, и список обязан
   * показать отказ со ссылкой в настройки. Отличать такое состояние по
   * подстроке в заголовке — значит поломать его при первой правке текста.
   */
  isSmartProcessMissing: boolean
}

export function describeBddsError(error: unknown): BddsErrorView {
  const status = readErrorStatus(error)
  const code = readErrorCode(error)
  const payload = readErrorPayload(error)
  const serverText = String(payload.error || '').trim()

  if (isRateLimitError(error)) {
    return {
      title: RATE_LIMIT_NOTICE_TEXT,
      hint: '',
      isFeatureDisabled: false,
      isProjectMissing: false,
      isSmartProcessMissing: false,
    }
  }

  if (code === 'feature_disabled' || status === 403) {
    return {
      title: serverText || 'Функция «БДДС по проектам» не подключена на этом портале.',
      hint: 'Подписку включает администратор приложения.',
      isFeatureDisabled: true,
      isProjectMissing: false,
      isSmartProcessMissing: false,
    }
  }

  if (code === 'project_not_found' || status === 404) {
    return {
      title: serverText || 'Проект не найден.',
      hint: 'Возможно, карточка проекта ещё не синхронизирована с портала — откройте «Проекты» и обновите доску.',
      isFeatureDisabled: false,
      isProjectMissing: true,
      isSmartProcessMissing: false,
    }
  }

  if (code === 'finance_spa_not_configured' || status === 409) {
    return {
      title: serverText || 'Смарт-процесс «Доходы-расходы» не настроен.',
      hint: 'План и факт по часам считаются и без него, а поступления и внешние платежи не видны. Настроить — «Сопоставление полей», шаг «Доходы-расходы».',
      isFeatureDisabled: false,
      isProjectMissing: false,
      isSmartProcessMissing: true,
    }
  }

  if (status && status >= 500) {
    return {
      title: serverText || 'Сервер не смог собрать бюджет проектов.',
      hint: 'Повторите через минуту. Если повторяется — «Настройки → Диагностика системы».',
      isFeatureDisabled: false,
      isProjectMissing: false,
      isSmartProcessMissing: false,
    }
  }

  return {
    title: serverText || 'Не удалось получить бюджет проектов.',
    hint: '',
    isFeatureDisabled: false,
    isProjectMissing: false,
    isSmartProcessMissing: false,
  }
}
