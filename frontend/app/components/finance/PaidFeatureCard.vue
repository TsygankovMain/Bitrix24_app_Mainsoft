<script setup lang="ts">
/**
 * Карточка платной функции: что она делает и что делать человеку.
 *
 * Была разметкой внутри pages/finance/[feature].client.vue. Вынесена, когда у
 * «Счёта и акта» появился настоящий экран: при выключенной подписке он обязан
 * показывать РОВНО ту же заглушку, что и раньше. Копия этой разметки на двух
 * страницах разошлась бы на первой же правке формулировки — а формулировка
 * здесь и есть весь смысл заглушки.
 *
 * Компонент только рисует. Состояние (замок, бейдж, подсказка) считает
 * resolvePaidFeatureState в app/utils/paidFeatures.ts, тексты лежат там же.
 */
import { computed } from 'vue'
import LockIcon from '@bitrix24/b24icons-vue/main/LockIcon'
import { resolvePaidFeatureState, type PaidFeatureId } from '~/utils/paidFeatures'

const props = withDefaults(defineProps<{
  featureId: PaidFeatureId
  /** Функция доступна: замка и бейджа «по подписке» нет. */
  enabled: boolean
  /**
   * Бейдж вместо стандартного. Нужен пробному периоду («пробный, осталось N
   * дней»): функция включена, но срок конечен. undefined — как решит
   * resolvePaidFeatureState.
   */
  badge?: string | null
}>(), {
  badge: undefined,
})

const state = computed(() => resolvePaidFeatureState(props.featureId, props.enabled))

const shownBadge = computed(() => props.badge === undefined ? state.value.badge : props.badge)
</script>

<template>
  <B24Card>
    <template #header>
      <div class="flex flex-wrap items-center gap-2">
        <LockIcon v-if="state.locked" class="size-5 text-slate-400" aria-hidden="true" />
        <span class="text-base font-semibold text-slate-900">{{ state.feature.label }}</span>
        <span
          v-if="shownBadge"
          class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
        >
          {{ shownBadge }}
        </span>
      </div>
    </template>

    <p class="text-sm text-slate-700">{{ state.feature.benefit }}</p>

    <ul class="mt-4 space-y-2">
      <li
        v-for="(detail, index) in state.feature.details"
        :key="index"
        class="flex gap-2 text-sm text-slate-600"
      >
        <span class="mt-2 size-1.5 shrink-0 rounded-full bg-slate-300" aria-hidden="true" />
        <span>{{ detail }}</span>
      </li>
    </ul>

    <template #footer>
      <slot name="footer">
        <p v-if="state.hint" class="text-sm text-slate-500">{{ state.hint }}</p>
        <p v-else class="text-sm text-slate-500">
          Функция подключена. Экран появится в этом разделе.
        </p>
      </slot>
    </template>
  </B24Card>
</template>
