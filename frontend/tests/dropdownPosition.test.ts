import test from 'node:test'
import assert from 'node:assert/strict'

import {
  computeDropdownPosition,
  DEFAULT_DROPDOWN_GAP,
  DEFAULT_DROPDOWN_VIEWPORT_PADDING,
} from '../app/utils/dropdownPosition'

// --- computeDropdownPosition ---
//
// Бриф хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
// hotfix-dropdown-clipping-brief.md): SearchableSelect.vue рисовал открытый
// список через position:absolute внутри якоря — B24Modal оборачивает
// содержимое двумя отсекающими контейнерами (overflow-y-auto и
// overflow-hidden), и список с результатами поиска (высотой ~370px) обрезался
// примерно на 180px, а внешний overflow:hidden не давал прокрутить до
// обрезанного. Фикс — телепорт в body с position:fixed, координаты которого
// считает эта функция.
//
// maxHeight в каждой ветке — это ДОСТУПНОЕ МЕСТО в выбранную сторону, а не
// desiredHeight: так работает и когда контента меньше, чем места (панель
// просто не дорастёт до потолка — max-height ограничивает сверху, но не
// растягивает), и защищает от рассинхрона, если высота содержимого изменится
// между пересчётами (список подрастёт после ответа сервера) чуть раньше, чем
// успеет прийти следующий пересчёт: потолок и так уже достаточно щедрый.

test('computeDropdownPosition: места хватает снизу — раскрывается вниз, maxHeight равен месту под якорем', () => {
  const result = computeDropdownPosition({
    anchor: { top: 200, bottom: 240, left: 50, width: 300 },
    desiredHeight: 300,
    viewportHeight: 800,
  })

  // spaceBelow = 800 - 8(padding) - 8(gap) - 240 = 544
  assert.deepEqual(result, {
    direction: 'down',
    top: 248, // anchor.bottom(240) + gap(8)
    left: 50,
    width: 300,
    maxHeight: 544,
  })
})

test('computeDropdownPosition: снизу не хватает, сверху хватает — переворачивается вверх', () => {
  const result = computeDropdownPosition({
    anchor: { top: 600, bottom: 640, left: 20, width: 280 },
    desiredHeight: 300,
    viewportHeight: 700,
  })

  // spaceBelow = 700 - 8 - 8 - 640 = 44 (< 300, не хватает)
  // spaceAbove = 600 - 8 - 8 = 584 (>= 300, хватает)
  assert.equal(result.direction, 'up')
  assert.equal(result.top, 292) // anchor.top(600) - gap(8) - desiredHeight(300)
  assert.equal(result.left, 20)
  assert.equal(result.width, 280)
  assert.equal(result.maxHeight, 584)
})

test('computeDropdownPosition: не хватает нигде, снизу места больше — раскрывается вниз с урезанным maxHeight', () => {
  const result = computeDropdownPosition({
    anchor: { top: 100, bottom: 150, left: 0, width: 200 },
    desiredHeight: 1000,
    viewportHeight: 500,
  })

  // spaceBelow = 500 - 8 - 8 - 150 = 334, spaceAbove = 100 - 8 - 8 = 84.
  // Оба меньше desiredHeight (1000) — но снизу места больше, значит вниз.
  assert.equal(result.direction, 'down')
  assert.equal(result.top, 158) // anchor.bottom(150) + gap(8)
  assert.equal(result.maxHeight, 334)
})

test('computeDropdownPosition: не хватает нигде, сверху места больше — переворачивается вверх с урезанным maxHeight', () => {
  const result = computeDropdownPosition({
    anchor: { top: 550, bottom: 580, left: 0, width: 200 },
    desiredHeight: 1000,
    viewportHeight: 600,
  })

  // spaceBelow = 600 - 8 - 8 - 580 = 4, spaceAbove = 550 - 8 - 8 = 534.
  assert.equal(result.direction, 'up')
  assert.equal(result.maxHeight, 534)
  // Верх панели упирается в верхний отступ окна (её низ приклеен к якорю).
  assert.equal(result.top, DEFAULT_DROPDOWN_VIEWPORT_PADDING)
})

test('computeDropdownPosition: не хватает нигде, места поровну — детерминированно выбирает низ', () => {
  const result = computeDropdownPosition({
    anchor: { top: 254, bottom: 254, left: 0, width: 200 },
    desiredHeight: 1000,
    viewportHeight: 508,
  })

  // spaceBelow = 508 - 8 - 8 - 254 = 238, spaceAbove = 254 - 8 - 8 = 238 — поровну.
  assert.equal(result.direction, 'down')
  assert.equal(result.maxHeight, 238)
})

test('computeDropdownPosition: якорь частично выше окна, снизу места достаточно — раскрывается вниз без сбоев', () => {
  const result = computeDropdownPosition({
    anchor: { top: -40, bottom: 10, left: 5, width: 150 },
    desiredHeight: 200,
    viewportHeight: 800,
  })

  // Отрицательный anchor.top не должен ничего ломать в ветке "вниз" — она
  // от него не зависит.
  assert.equal(result.direction, 'down')
  assert.equal(result.top, 18) // anchor.bottom(10) + gap(8)
  assert.equal(result.maxHeight, 774)
})

test('computeDropdownPosition: якорь почти целиком выше окна и места нигде почти нет — maxHeight не уходит в минус', () => {
  const result = computeDropdownPosition({
    anchor: { top: -40, bottom: 780, left: 0, width: 100 },
    desiredHeight: 100,
    viewportHeight: 800,
  })

  // spaceAbove "по формуле" был бы -40 - 8 - 8 = -56 — без Math.max(0, ...)
  // это отрицательное число могло бы просочиться в сравнение или в maxHeight.
  // spaceBelow = 800 - 8 - 8 - 780 = 4.
  assert.equal(result.direction, 'down') // 4 >= 0
  assert.equal(result.maxHeight, 4)
  assert.ok(result.maxHeight >= 0, 'высота панели не должна быть отрицательной')
})

test('computeDropdownPosition: ширина и левый край всегда берутся из якоря, независимо от направления', () => {
  const down = computeDropdownPosition({
    anchor: { top: 10, bottom: 50, left: 123, width: 456 },
    desiredHeight: 50,
    viewportHeight: 900,
  })
  const up = computeDropdownPosition({
    anchor: { top: 850, bottom: 890, left: 123, width: 456 },
    desiredHeight: 50,
    viewportHeight: 900,
  })

  assert.equal(down.left, 123)
  assert.equal(down.width, 456)
  assert.equal(up.left, 123)
  assert.equal(up.width, 456)
})

test('computeDropdownPosition: переданные gap/viewportPadding используются вместо значений по умолчанию', () => {
  const result = computeDropdownPosition({
    anchor: { top: 200, bottom: 240, left: 0, width: 100 },
    desiredHeight: 50,
    viewportHeight: 800,
    gap: 20,
    viewportPadding: 40,
  })

  assert.equal(result.top, 260) // anchor.bottom(240) + gap(20), а не +8
  assert.equal(result.maxHeight, 500) // 800 - 40 - 20 - 240
})

test('computeDropdownPosition: без явных gap/viewportPadding действуют экспортированные значения по умолчанию', () => {
  assert.equal(DEFAULT_DROPDOWN_GAP, 8)
  assert.equal(DEFAULT_DROPDOWN_VIEWPORT_PADDING, 8)
})
