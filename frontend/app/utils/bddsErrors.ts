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
    }
  }

  if (code === 'feature_disabled' || status === 403) {
    return {
      title: serverText || 'Функция «БДДС по проектам» не подключена на этом портале.',
      hint: 'Подписку включает администратор приложения.',
      isFeatureDisabled: true,
      isProjectMissing: false,
    }
  }

  if (code === 'project_not_found' || status === 404) {
    return {
      title: serverText || 'Проект не найден.',
      hint: 'Возможно, карточка проекта ещё не синхронизирована с портала — откройте «Проекты» и обновите доску.',
      isFeatureDisabled: false,
      isProjectMissing: true,
    }
  }

  if (code === 'finance_spa_not_configured' || status === 409) {
    return {
      title: serverText || 'Смарт-процесс «Доходы-расходы» не настроен.',
      hint: 'План и факт по часам считаются и без него, а поступления и внешние платежи не видны. Настроить — «Настройки → Настройка полей».',
      isFeatureDisabled: false,
      isProjectMissing: false,
    }
  }

  if (status && status >= 500) {
    return {
      title: serverText || 'Сервер не смог собрать бюджет проектов.',
      hint: 'Повторите через минуту. Если повторяется — «Настройки → Диагностика системы».',
      isFeatureDisabled: false,
      isProjectMissing: false,
    }
  }

  return {
    title: serverText || 'Не удалось получить бюджет проектов.',
    hint: '',
    isFeatureDisabled: false,
    isProjectMissing: false,
  }
}
