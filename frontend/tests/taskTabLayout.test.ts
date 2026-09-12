import test from 'node:test'
import assert from 'node:assert/strict'

import {
  TASK_TAB_MEDIUM_FROM,
  TASK_TAB_WIDE_FROM,
  TASK_TAB_XWIDE_FROM,
  resolveTaskTabLayout,
  taskTabIndent,
  taskTabLayoutClass
} from '../app/utils/taskTabLayout'

test('resolveTaskTabLayout: от 900 px показывается всё — итоги справа и подписи действий', () => {
  const layout = resolveTaskTabLayout(1000)

  assert.equal(layout.mode, 'xwide')
  assert.equal(layout.inlineEntryMeta, true)
  assert.equal(layout.stackedTaskTotals, false)
  assert.equal(layout.iconOnlyEntryActions, false)
  assert.equal(layout.stackedFilters, false)
})

test('resolveTaskTabLayout: на 660 итоги уходят под название, а действия — в иконки', () => {
  const layout = resolveTaskTabLayout(660)

  assert.equal(layout.mode, 'wide')
  assert.equal(layout.stackedTaskTotals, true, 'с итогами справа названию задачи оставалось 136 px')
  assert.equal(layout.iconOnlyEntryActions, true, 'с подписями описанию записи оставалось 114 px')
  assert.equal(layout.inlineEntryMeta, true)
})

test('resolveTaskTabLayout: три контрольные ширины редизайна — 660, 480 и 400', () => {
  assert.equal(resolveTaskTabLayout(660).mode, 'wide')
  assert.equal(resolveTaskTabLayout(480).mode, 'medium')
  assert.equal(resolveTaskTabLayout(400).mode, 'narrow')
})

test('resolveTaskTabLayout: границы включают нижнее значение и не включают соседнее', () => {
  assert.equal(resolveTaskTabLayout(TASK_TAB_XWIDE_FROM).mode, 'xwide')
  assert.equal(resolveTaskTabLayout(TASK_TAB_XWIDE_FROM - 1).mode, 'wide')
  assert.equal(resolveTaskTabLayout(TASK_TAB_WIDE_FROM).mode, 'wide')
  assert.equal(resolveTaskTabLayout(TASK_TAB_WIDE_FROM - 1).mode, 'medium')
  assert.equal(resolveTaskTabLayout(TASK_TAB_MEDIUM_FROM).mode, 'medium')
  assert.equal(resolveTaskTabLayout(TASK_TAB_MEDIUM_FROM - 1).mode, 'narrow')
})

test('resolveTaskTabLayout: на 480 фильтр ещё строкой, а мета записи уже под описанием', () => {
  const layout = resolveTaskTabLayout(480)

  assert.equal(layout.stackedFilters, false)
  assert.equal(layout.stackedTaskTotals, true)
  assert.equal(layout.inlineEntryMeta, false, 'в строке описанию осталось бы около 125 px')
  assert.equal(layout.iconOnlyEntryActions, true)
})

test('resolveTaskTabLayout: на 400 всё складывается в колонку', () => {
  const layout = resolveTaskTabLayout(400)

  assert.equal(layout.inlineEntryMeta, false)
  assert.equal(layout.stackedTaskTotals, true)
  assert.equal(layout.stackedFilters, true)
})

test('resolveTaskTabLayout: до первого измерения ширины отдаётся широкая раскладка', () => {
  assert.equal(resolveTaskTabLayout(0).mode, 'wide')
  assert.equal(resolveTaskTabLayout(-100).mode, 'wide')
  assert.equal(resolveTaskTabLayout(Number.NaN).mode, 'wide')
})

test('taskTabLayoutClass: класс-модификатор по режиму', () => {
  assert.equal(taskTabLayoutClass('wide'), 'task-tab--wide')
  assert.equal(taskTabLayoutClass('narrow'), 'task-tab--narrow')
})

test('taskTabIndent: отступ растёт по уровням, но упирается в потолок', () => {
  const wide = resolveTaskTabLayout(700)

  assert.equal(taskTabIndent(0, wide), 0)
  assert.equal(taskTabIndent(1, wide), 16)
  assert.equal(taskTabIndent(3, wide), 48)
  assert.equal(taskTabIndent(7, wide), 48, 'седьмой уровень не должен съедать ширину дальше третьего')
})

test('taskTabIndent: на узком фрейме шаг отступа меньше', () => {
  const narrow = resolveTaskTabLayout(400)

  assert.equal(taskTabIndent(1, narrow), 6)
  assert.equal(taskTabIndent(5, narrow), 18)
})
