import test from 'node:test'
import assert from 'node:assert/strict'

import { extractMixedCompanies } from '../app/utils/billingCompanies'

test('extractMixedCompanies: пары id/name из предупреждения становятся кнопками', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      companies: [
        { id: '1758', name: 'ООО «Ромашка»' },
        { id: '1766', name: 'АО «Василёк»' },
      ],
    },
  })

  assert.deepEqual(result, [
    { id: '1758', label: 'ООО «Ромашка»', named: true },
    { id: '1766', label: 'АО «Василёк»', named: true },
  ])
})

test('extractMixedCompanies: сервер подставил id вместо названия — показываем id', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      companies: [{ id: '2568', name: '2568' }],
    },
  })

  assert.deepEqual(result, [{ id: '2568', label: '2568', named: false }])
})

test('extractMixedCompanies: название берётся из справочника экрана', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      companies: [{ id: '2568', name: '2568' }],
    },
    directory: [{ id: '2568', name: 'ООО «Мастер»' }],
  })

  assert.deepEqual(result, [{ id: '2568', label: 'ООО «Мастер»', named: true }])
})

test('extractMixedCompanies: числовые details тоже дают идентификаторы', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      details: ['1758', '1766', '2568'],
    },
  })

  assert.deepEqual(result.map(item => item.id), ['1758', '1766', '2568'])
  assert.equal(result.every(item => item.named === false), true)
})

test('extractMixedCompanies: названия без идентификаторов в кнопки не превращаются', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      details: ['ООО «Ромашка»', 'АО «Василёк»'],
    },
  })

  assert.deepEqual(result, [])
})

test('extractMixedCompanies: список из ответа preview работает без предупреждения', () => {
  const result = extractMixedCompanies({
    warning: { code: 'mixed_companies' },
    companies: [{ id: '11', name: 'Первый' }, { id: '22', name: 'Второй' }],
  })

  assert.deepEqual(result.map(item => item.label), ['Первый', 'Второй'])
})

test('extractMixedCompanies: повторы схлопываются, порядок сохраняется', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      companies: [
        { id: '5', name: 'Пятый' },
        { id: '5', name: 'Пятый' },
        { id: '3', name: 'Третий' },
      ],
    },
  })

  assert.deepEqual(result.map(item => item.id), ['5', '3'])
})

test('extractMixedCompanies: пустой вход — пустой список, без выдумок', () => {
  assert.deepEqual(extractMixedCompanies({}), [])
  assert.deepEqual(extractMixedCompanies({ warning: null, companies: null, directory: null }), [])
})

test('extractMixedCompanies: записи без идентификатора пропускаются', () => {
  const result = extractMixedCompanies({
    warning: {
      code: 'mixed_companies',
      companies: [{ id: '', name: 'Безымянный' }, { id: '9', name: 'Девятый' }],
    },
  })

  assert.deepEqual(result.map(item => item.id), ['9'])
})
