import { test } from 'node:test'
import assert from 'node:assert'
import { normalizeEnvLabel, withEnvLabel } from '../app/utils/envLabel'

test('envLabel: без аргумента сборки метки нет', () => {
  assert.equal(normalizeEnvLabel(undefined), '')
  assert.equal(normalizeEnvLabel(null), '')
  assert.equal(normalizeEnvLabel(''), '')
  assert.equal(normalizeEnvLabel('   '), '')
})

test('envLabel: значение обрезается по краям', () => {
  assert.equal(normalizeEnvLabel(' DEV_ver2 '), 'DEV_ver2')
})

test('envLabel: заголовок вкладки получает префикс только с меткой', () => {
  assert.equal(withEnvLabel('Учёт трудозатрат', 'DEV_ver2'), '[DEV_ver2] Учёт трудозатрат')
  assert.equal(withEnvLabel('Учёт трудозатрат', ''), 'Учёт трудозатрат')
})
