/**
 * Контраст цветовых пар вкладки задачи — по формуле WCAG 2.1 (1.4.3, уровень AA).
 *
 * Зачем считать, а не «смотреть глазами». Штатная кнопка Bitrix24 UI Kit
 * `color="air-primary"` — это белый текст на `--ui-color-accent-main-primary`
 * (#0075ff): 4.21:1, ниже нормы AA 4.5:1 для обычного текста. Прежняя вкладка
 * задачи была ещё хуже: тёмный текст #0f172a на том же синем даёт 4.24:1.
 * Оба варианта на глаз выглядят прилично, и без расчёта дефект не виден.
 *
 * Решение: во вкладке задачи токен заливки акцентных кнопок переопределён на
 * `--ui-color-blue-80` (#0069e6) — тот же синий ряд палитры Air, но на шаг
 * темнее; белый текст на нём даёт 5.04:1. Перечень пар ниже повторяет то, что
 * реально написано в стилях `pages/embedded.vue` и `components/task/*`, а тест
 * не даёт молча вернуть недоступное сочетание.
 */

export interface ContrastPair {
  /** Где встречается пара — по этому имени ищется место в стилях. */
  name: string
  foreground: string
  background: string
  /** Минимум по WCAG: 4.5 для обычного текста, 3 для крупного и для иконок. */
  minRatio: number
}

function parseHex(value: string): [number, number, number] {
  const raw = String(value || '').trim().replace(/^#/, '')
  const expanded = raw.length === 3
    ? raw.split('').map(char => char + char).join('')
    : raw

  if (!/^[0-9a-fA-F]{6}$/.test(expanded)) {
    throw new Error(`Не цвет в формате #rrggbb: ${value}`)
  }

  return [
    Number.parseInt(expanded.slice(0, 2), 16),
    Number.parseInt(expanded.slice(2, 4), 16),
    Number.parseInt(expanded.slice(4, 6), 16)
  ]
}

/** Относительная яркость по WCAG 2.1. */
export function relativeLuminance(hex: string): number {
  const [red, green, blue] = parseHex(hex)
  const channel = (value: number) => {
    const normalized = value / 255
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  }

  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
}

/** Коэффициент контраста двух цветов, от 1 до 21. */
export function contrastRatio(first: string, second: string): number {
  const a = relativeLuminance(first)
  const b = relativeLuminance(second)
  const lighter = Math.max(a, b)
  const darker = Math.min(a, b)

  return (lighter + 0.05) / (darker + 0.05)
}

/** Белый текст на акцентной кнопке вкладки задачи: #0069e6 — это --ui-color-blue-80. */
export const TASK_TAB_ACCENT_BG = '#0069e6'
export const TASK_TAB_ACCENT_HOVER_BG = '#035ea8'

/** Пары, которые реально используются в стилях вкладки задачи. */
export const TASK_TAB_CONTRAST_PAIRS: ContrastPair[] = [
  { name: 'Акцентная кнопка: белый текст', foreground: '#ffffff', background: TASK_TAB_ACCENT_BG, minRatio: 4.5 },
  { name: 'Акцентная кнопка (наведение): белый текст', foreground: '#ffffff', background: TASK_TAB_ACCENT_HOVER_BG, minRatio: 4.5 },
  { name: 'Основной текст на карточке', foreground: '#333333', background: '#ffffff', minRatio: 4.5 },
  { name: 'Второстепенный текст на карточке', foreground: '#525c69', background: '#ffffff', minRatio: 4.5 },
  { name: 'Второстепенный текст на шапке задачи', foreground: '#525c69', background: '#f1f4f6', minRatio: 4.5 },
  { name: 'Учтённые часы', foreground: '#058449', background: '#ffffff', minRatio: 4.5 },
  { name: 'Неучтённые часы', foreground: '#c21b16', background: '#ffffff', minRatio: 4.5 },
  { name: 'Кнопка удаления записи', foreground: '#c21b16', background: '#ffffff', minRatio: 4.5 },
  { name: 'Кнопка правки записи', foreground: '#0154c8', background: '#ffffff', minRatio: 4.5 },
  { name: 'Метка «Подзадача» и активная быстрая кнопка', foreground: '#0154c8', background: '#e6f4ff', minRatio: 4.5 },
  { name: 'Ошибка формы на голубой подложке', foreground: '#c21b16', background: '#edf7ff', minRatio: 4.5 },
  { name: 'Баннер ошибки вкладки', foreground: '#c21b16', background: '#fff0f0', minRatio: 4.5 }
]
