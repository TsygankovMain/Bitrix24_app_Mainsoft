<script setup lang="ts">
/**
 * Карточка закрытой платной функции: замок, бейдж «Pro», польза, цена и
 * кнопка «Подключить Pro».
 *
 * Вид ОДИН на все платные функции (БДДС, счёт и акт, ролевая модель) и на
 * все места, где функция закрыта: заглушка /finance/<id>, экраны за
 * BillingGate / BddsGate и экран ролевой модели. Копия разметки разошлась
 * бы на первой же правке формулировки.
 *
 * Кнопка ведёт на /pro (app/pages/pro.client.vue) — пока это заглушка, позже
 * там будет форма запроса счёта. Адрес и тексты — app/utils/proPlan.ts.
 *
 * Компонент только рисует. Состояние (замок, бейдж, подсказку) считает
 * resolvePaidFeatureState / resolveFeatureAccess.
 */
import { computed } from 'vue'
import LockIcon from '@bitrix24/b24icons-vue/main/LockIcon'
import { resolvePaidFeatureState, type PaidFeatureId } from '~/utils/paidFeatures'
import { PRO_CTA_LABEL, proPriceText, proRoute } from '~/utils/proPlan'

const props = withDefaults(defineProps<{
  featureId: PaidFeatureId
  /** Функция доступна: замка, бейджа «Pro», цены и кнопки нет. */
  enabled: boolean
  /** Бейдж вместо стандартного (например, «пробный, осталось N дней»). */
  badge?: string | null
  /** Цена в месяц с сервера (price_month_rub); по умолчанию 3000. */
  priceMonthRub?: number | null
}>(), {
  badge: undefined,
  priceMonthRub: null,
})

const router = useRouter()

const state = computed(() => resolvePaidFeatureState(props.featureId, props.enabled))

const shownBadge = computed(() => props.badge === undefined ? state.value.badge : props.badge)

const priceText = computed(() => proPriceText(props.priceMonthRub ?? undefined))

function openPro() {
  void router.push(proRoute(props.featureId))
}
</script>

<template>
  <B24Card>
    <template #header>
      <div class="flex flex-wrap items-center gap-2">
        <LockIcon v-if="state.locked" class="size-5 text-slate-400" aria-hidden="true" />
        <span class="text-base font-semibold text-slate-900">{{ state.feature.label }}</span>
        <span
          v-if="shownBadge"
          class="rounded-full bg-[#0075ff] px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white"
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
      <div v-if="state.locked" class="flex flex-wrap items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-sm font-semibold text-slate-900">{{ priceText }}</p>
          <p class="text-xs text-slate-500">
            Тариф Pro открывает все платные функции: БДДС, счёт и акт, ролевую модель.
          </p>
        </div>
        <B24Button :label="PRO_CTA_LABEL" color="primary" @click="openPro" />
      </div>
      <slot name="footer">
        <p v-if="!state.locked" class="text-sm text-slate-500">
          Функция подключена. Экран появится в этом разделе.
        </p>
      </slot>
    </template>
  </B24Card>
</template>
