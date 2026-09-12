<script setup lang="ts">
/**
 * Полоса итогов отчёта — «вариант A: родной портал».
 *
 * До редизайна итоги были сеткой карточек `ms-kpi-grid` (по три-шесть штук в
 * ряд, каждая с рамкой и тенью) и занимали экран до самой таблицы. В макете
 * итоги — одна строка над таблицей, в том же блоке, что и свежесть данных:
 * человек видит «всего / учтено / не учтено / учтённость» одним взглядом и
 * сразу под ними — строки, из которых это сложилось.
 *
 * ЦИФРЫ КОМПОНЕНТ НЕ СЧИТАЕТ. Он печатает то, что отчёт уже посчитал, — иначе
 * при переносе итогов из карточек в строку значения могли бы разойтись с
 * таблицей.
 */

export type ReportTotalTone = 'default' | 'success' | 'warning' | 'danger' | 'info'

export type ReportTotal = {
  id: string
  label: string
  value: string | number
  caption?: string
  tone?: ReportTotalTone
}

defineProps<{
  items: ReportTotal[]
}>()

const TONE_CLASS: Record<ReportTotalTone, string> = {
  default: 'text-slate-900',
  success: 'text-emerald-700',
  warning: 'text-amber-700',
  danger: 'text-rose-700',
  info: 'text-sky-700',
}

function toneClass(tone?: ReportTotalTone): string {
  return TONE_CLASS[tone || 'default']
}
</script>

<template>
  <dl
    v-if="items.length"
    class="flex flex-wrap items-stretch gap-x-8 gap-y-3 rounded-2xl border border-slate-200 bg-white px-4 py-3"
  >
    <div v-for="item in items" :key="item.id" class="min-w-[104px]">
      <dt class="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
        {{ item.label }}
      </dt>
      <dd class="mt-0.5 text-lg font-bold tabular-nums" :class="toneClass(item.tone)">
        {{ item.value }}
      </dd>
      <dd v-if="item.caption" class="text-xs text-slate-500">
        {{ item.caption }}
      </dd>
    </div>
  </dl>
</template>
