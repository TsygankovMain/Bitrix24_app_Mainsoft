import test from 'node:test'
import assert from 'node:assert/strict'

import { describeBddsError } from '../app/utils/bddsErrors'

function httpError(status: number, payload: Record<string, unknown> = {}) {
  return { response: { status, _data: payload }, status, data: payload }
}

test('отказ по подписке помечается отдельно: экран показывает замок, а не плашку', () => {
  const view = describeBddsError(httpError(403, {
    error: 'Функция «БДДС по проектам» не подключена на этом портале.',
    code: 'feature_disabled',
    feature: 'bdds',
  }))

  assert.equal(view.isFeatureDisabled, true)
  assert.match(view.title, /БДДС по проектам/)
  assert.match(view.hint, /Pro/)
})

test('проект не найден — подсказка ведёт к синхронизации, а не в поддержку', () => {
  const view = describeBddsError(httpError(404, {
    error: 'Проект не найден в карточках проектов.',
    code: 'project_not_found',
  }))

  assert.equal(view.isProjectMissing, true)
  assert.match(view.hint, /синхронизирован/)
})

test('ненастроенный смарт-процесс: план и факт по часам всё равно считаются', () => {
  const view = describeBddsError(httpError(409, {
    error: 'Finance SPA is not configured',
    code: 'finance_spa_not_configured',
  }))

  assert.equal(view.isFeatureDisabled, false)
  assert.match(view.hint, /по часам считаются/)
})

test('лимитер отвечает «подождите минуту», а не сообщением об ошибке', () => {
  const view = describeBddsError(httpError(429))

  assert.match(view.title, /Слишком много запросов/)
  assert.equal(view.isFeatureDisabled, false)
})

test('пятисотка: текст сервера плюс подсказка про диагностику', () => {
  const view = describeBddsError(httpError(500, { error: 'Внутренняя ошибка сервера' }))

  assert.equal(view.title, 'Внутренняя ошибка сервера')
  assert.match(view.hint, /Диагностика/)
})

test('неизвестная ошибка не показывает машинное сообщение ofetch', () => {
  const view = describeBddsError(new Error('[GET] "/api/bdds/projects": <no response>'))

  assert.equal(view.title, 'Не удалось получить бюджет проектов.')
  assert.equal(view.hint, '')
})

test('409 finance_operation_busy — это занятое сохранение, а не ненастроенный смарт-процесс', () => {
  const view = describeBddsError(httpError(409, {
    error: 'Кто-то уже сохраняет операцию по этому смарт-процессу. Повторите через несколько секунд.',
    code: 'finance_operation_busy',
  }))
  assert.equal(view.isSmartProcessMissing, false)
  assert.match(view.title, /уже сохраняет/)
})
