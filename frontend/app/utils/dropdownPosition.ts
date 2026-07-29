/**
 * Чистая логика позиционирования выпадающего списка SearchableSelect.vue
 * (см. frontend/app/components/common/SearchableSelect.vue).
 *
 * Бриф хотфикса 2026-07-29 (см. .superpowers/sdd/2026-07-28-create-project-button/
 * hotfix-dropdown-clipping-brief.md): список рисовался через position:absolute
 * внутри поля-якоря. B24Modal оборачивает содержимое двумя отсекающими
 * контейнерами (overflow-y-auto тела окна и overflow-hidden обёртки) —
 * список с результатами поиска компаний (~370px) обрезался примерно на
 * 180px, а внешний overflow:hidden не давал прокрутить до обрезанного.
 *
 * Фикс — телепорт панели в body с position:fixed; координаты для него
 * (относительно viewport, как и getBoundingClientRect) считает эта функция.
 * Вынесена из компонента намеренно: node:test через tsx не резолвит .vue, а
 * это ровно та часть фичи (направление вверх/вниз, верхняя граница,
 * доступная высота), которую стоит и можно проверить без DOM — единственное,
 * что компоненту нужно измерить самому, это прямоугольник якоря
 * (rootRef.getBoundingClientRect()) и желаемую высоту содержимого панели.
 */

export interface DropdownAnchorRect {
  top: number
  bottom: number
  left: number
  width: number
}

export interface ComputeDropdownPositionInput {
  /** Прямоугольник поля-якоря (rootRef.getBoundingClientRect() в компоненте).
   * Достаточно top/bottom/left/width — обычный DOMRect тоже подходит, лишние
   * поля (right/height/x/y) не мешают. */
  anchor: DropdownAnchorRect
  /** Желаемая высота панели БЕЗ ограничений — сколько она заняла бы, если бы
   * её ничего не подрезало (шапка с полем поиска + перечень целиком).
   * Компонент измеряет её из живого DOM на каждый пересчёт (высота шапки +
   * scrollHeight прокручиваемого перечня — оно не зависит от уже применённого
   * max-height, см. докстринг измерения в SearchableSelect.vue). Используется
   * только чтобы решить, поместится ли панель целиком в выбранную сторону —
   * не путать с maxHeight результата (см. ниже). */
  desiredHeight: number
  /** Высота окна браузера — window.innerHeight на момент пересчёта. */
  viewportHeight: number
  /** Зазор между полем-якорем и панелью. По умолчанию 8px — то же расстояние,
   * что раньше задавал Tailwind-класс mt-2. */
  gap?: number
  /** Минимальный отступ панели от края окна браузера — даже когда места
   * впритык, панель не должна вплотную прилипать к самой рамке окна. */
  viewportPadding?: number
}

export type DropdownDirection = 'down' | 'up'

export interface DropdownPositionResult {
  /** Сторона от якоря, куда раскрывается панель. */
  direction: DropdownDirection
  /** Верхняя граница панели в координатах viewport (совместимо с
   * position:fixed для элемента, телепортированного в body). */
  top: number
  /** Левая граница панели — всегда совпадает с левой границей якоря. */
  left: number
  /** Ширина панели — всегда совпадает с шириной якоря (требование 1 брифа). */
  width: number
  /**
   * Ограничение высоты панели — это ДОСТУПНОЕ МЕСТО в выбранную сторону, а
   * не desiredHeight. Так работает в обоих случаях: когда содержимого меньше,
   * чем места (max-height — это потолок, а не принудительная растяжка,
   * панель просто не дорастёт до него), и когда десктоп-содержимое подрастёт
   * между пересчётами позиции (например, список только что открылся почти
   * пустым, а через 300ms дебаунса пришли 50 результатов) — щедрый потолок,
   * посчитанный от реального места на экране, не обрезает выросшее
   * содержимое даже если пересчёт высоты чуть отстаёт от пересчёта позиции.
   */
  maxHeight: number
}

/** То же расстояние, что раньше задавал Tailwind-класс mt-2 (0.5rem). */
export const DEFAULT_DROPDOWN_GAP = 8

/** Небольшой отступ от рамки окна браузера, даже когда места впритык. */
export const DEFAULT_DROPDOWN_VIEWPORT_PADDING = 8

/**
 * Решает, раскрывать ли выпадающий список вниз или вверх, и сколько места
 * ему доступно, по прямоугольнику поля-якоря, желаемой высоте содержимого и
 * высоте окна браузера.
 *
 * Правило:
 *  1. Помещается целиком снизу (spaceBelow >= desiredHeight) — вниз.
 *  2. Не помещается снизу, но помещается целиком сверху — переворот вверх
 *     (требование 2 брифа).
 *  3. Не помещается целиком ни туда, ни туда — сторона с бОльшим свободным
 *     местом, высота ограничивается им же (внутренний перечень остаётся
 *     прокручиваемым — компонент не меняет max-height списка ниже этого
 *     потолка на статичный, см. требование 3 брифа). При точном равенстве
 *     мест — вниз (сохраняет прежнее визуальное поведение по умолчанию).
 *
 * spaceBelow/spaceAbove никогда не уходят в отрицательные числа (Math.max(0,
 * ...)) — иначе якорь, частично или полностью выехавший за границу окна
 * (проскроллили модалку с открытым списком), мог бы породить отрицательный
 * maxHeight или сломать сравнение "какая сторона больше".
 */
export function computeDropdownPosition(input: ComputeDropdownPositionInput): DropdownPositionResult {
  const gap = input.gap ?? DEFAULT_DROPDOWN_GAP
  const viewportPadding = input.viewportPadding ?? DEFAULT_DROPDOWN_VIEWPORT_PADDING
  const desiredHeight = Math.max(0, input.desiredHeight)

  const { anchor } = input
  const left = anchor.left
  const width = anchor.width

  const spaceBelow = Math.max(0, input.viewportHeight - viewportPadding - gap - anchor.bottom)
  const spaceAbove = Math.max(0, anchor.top - gap - viewportPadding)

  if (spaceBelow >= desiredHeight) {
    return { direction: 'down', top: anchor.bottom + gap, left, width, maxHeight: spaceBelow }
  }

  if (spaceAbove >= desiredHeight) {
    return { direction: 'up', top: anchor.top - gap - desiredHeight, left, width, maxHeight: spaceAbove }
  }

  if (spaceBelow >= spaceAbove) {
    return { direction: 'down', top: anchor.bottom + gap, left, width, maxHeight: spaceBelow }
  }

  return { direction: 'up', top: viewportPadding, left, width, maxHeight: spaceAbove }
}
