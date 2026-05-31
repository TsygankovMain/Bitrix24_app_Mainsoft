import { test } from 'node:test'
import assert from 'node:assert'
import { useProgress } from '../app/composables/useProgress'

test('progress: счётчик параллельных операций', () => {
  const p = useProgress()
  while (p.active.value) p.end()
  p.begin('A')
  assert.equal(p.active.value, true)
  assert.equal(p.state.title, 'A')
  p.begin('B', 10, 'подсказка')
  assert.equal(p.state.count, 2)
  assert.equal(p.state.total, 10)
  assert.equal(p.state.hint, 'подсказка')
  p.update(5)
  assert.equal(p.state.done, 5)
  // stage() меняет надпись/подсказку, не трогая счётчик
  p.stage('Шаг 2 из 2', 'формирование')
  assert.equal(p.state.title, 'Шаг 2 из 2')
  assert.equal(p.state.hint, 'формирование')
  assert.equal(p.state.count, 2)
  p.end()
  assert.equal(p.active.value, true)
  p.end()
  assert.equal(p.active.value, false)
  assert.equal(p.state.title, '')
  assert.equal(p.state.hint, '')
  assert.equal(p.state.total, 0)
})
