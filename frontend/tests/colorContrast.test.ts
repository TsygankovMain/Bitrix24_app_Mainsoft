import test from 'node:test'
import assert from 'node:assert/strict'

import {
  TASK_TAB_ACCENT_BG,
  TASK_TAB_CONTRAST_PAIRS,
  contrastRatio,
  relativeLuminance
} from '../app/utils/colorContrast'

test('relativeLuminance: крайние значения шкалы', () => {
  assert.equal(relativeLuminance('#ffffff'), 1)
  assert.equal(relativeLuminance('#000000'), 0)
})

test('contrastRatio: чёрный на белом — 21:1', () => {
  assert.equal(Math.round(contrastRatio('#000', '#fff')), 21)
})

test('contrastRatio: симметричен и не зависит от регистра записи', () => {
  assert.equal(contrastRatio('#0069E6', '#FFFFFF'), contrastRatio('#ffffff', '#0069e6'))
})

test('contrastRatio: прежние пары вкладки задачи не дотягивали до AA', () => {
  // Тёмный текст на синей кнопке — то, что было в embedded.vue до редизайна.
  assert.ok(contrastRatio('#0f172a', '#0075ff') < 4.5)
  // Белый текст на штатном акценте UI Kit тоже не проходит — поэтому во
  // вкладке задачи заливка кнопки переопределена на --ui-color-blue-80.
  assert.ok(contrastRatio('#ffffff', '#0075ff') < 4.5)
})

test('contrastRatio: новая акцентная кнопка проходит AA', () => {
  const ratio = contrastRatio('#ffffff', TASK_TAB_ACCENT_BG)

  assert.ok(ratio >= 4.5, `ожидали не меньше 4.5:1, получили ${ratio.toFixed(2)}`)
})

for (const pair of TASK_TAB_CONTRAST_PAIRS) {
  test(`контраст AA: ${pair.name}`, () => {
    const ratio = contrastRatio(pair.foreground, pair.background)

    assert.ok(
      ratio >= pair.minRatio,
      `${pair.foreground} на ${pair.background}: ${ratio.toFixed(2)}:1, нужно ${pair.minRatio}:1`
    )
  })
}

test('relativeLuminance: не цвет — это ошибка, а не молчаливый ноль', () => {
  assert.throws(() => relativeLuminance('rgb(0,0,0)'))
})
