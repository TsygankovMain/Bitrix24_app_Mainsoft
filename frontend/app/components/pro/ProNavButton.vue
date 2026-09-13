<script setup lang="ts">
/**
 * Кнопка «Купить Pro» справа от меню разделов (макет покупки Pro, экран 1.1).
 *
 * Контурная, не синяя: она постоянная, но не кричит. Цвет усиливается только
 * по поводу — Pro кончается (жёлтая «Продлить»), Pro истёк (красная). При
 * действующем Pro кнопки нет, остаётся бейдж «Pro до …». Если счёт уже
 * выставлен — «Счёт ждёт оплаты» ведёт на тот же счёт, а не на новую форму.
 *
 * На рабочих экранах (отчёты, вкладка задачи) кнопки нет —
 * shouldShowProNavButton. Состояние считает resolveProNavButton
 * (app/utils/proPurchase.ts), компонент только рисует.
 *
 * Свой запрос компонент делает только после бутстрапа: меню живёт в лейауте и
 * рисуется раньше, чем появился токен, поэтому ждём ответ /api/features.
 */
import { computed, watch } from 'vue'
import { PRO_ROUTE } from '~/utils/proPlan'
import { resolveProNavButton, shouldShowProNavButton, todayIso } from '~/utils/proPurchase'

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { features } = usePortalFeatures()
const { hasOpenRequest, loadCurrentRequest } = useProPurchase()

const subscription = computed(() => {
  const all = features.value
  if (!all) {
    return null
  }

  return all.billing || Object.values(all)[0] || null
})

watch(
  () => Boolean(features.value) && apiStore.hasToken,
  (ready) => {
    if (ready) {
      void loadCurrentRequest()
    }
  },
  { immediate: true }
)

const visible = computed(() => shouldShowProNavButton(route.path))

const state = computed(() => resolveProNavButton({
  subscription: subscription.value,
  openRequest: hasOpenRequest.value,
  today: todayIso(),
}))

const BADGE_CLASSES: Record<string, string> = {
  info: 'bg-[#e8f3ff] text-[#0058c2]',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-800',
  danger: 'bg-rose-50 text-rose-700',
  muted: 'bg-slate-100 text-slate-600',
}

const BUTTON_CLASSES: Record<string, string> = {
  outline: 'border-[#0075ff] text-[#0075ff] hover:bg-[#e8f3ff]',
  warning: 'border-amber-400 bg-amber-50 text-amber-900 hover:bg-amber-100',
  danger: 'border-rose-500 bg-rose-50 text-rose-700 hover:bg-rose-100',
  default: 'border-slate-300 text-slate-700 hover:bg-slate-50',
}

function openPro() {
  void router.push(PRO_ROUTE)
}
</script>

<template>
  <div v-if="visible" class="ml-2 flex shrink-0 items-center gap-2">
    <button
      v-if="state.badge"
      type="button"
      class="hidden whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-semibold min-[900px]:inline-flex"
      :class="BADGE_CLASSES[state.badgeTone]"
      title="Подписка на Pro"
      @click="openPro"
    >
      {{ state.badge }}
    </button>
    <button
      v-if="state.label"
      type="button"
      class="inline-flex h-[30px] items-center whitespace-nowrap rounded-lg border px-3 text-[13px] font-semibold transition"
      :class="BUTTON_CLASSES[state.tone]"
      @click="openPro"
    >
      {{ state.label }}
    </button>
  </div>
</template>
