<script setup lang="ts">
/**
 * Карточка «Подписка» — первая на странице настроек (макет, экран 1.3).
 *
 * Сюда приходят за сроком, номером последнего счёта и продлением. Сравнение
 * «Базовый / Pro» живёт только здесь — на замке закрытой функции оно было бы
 * лишним. Тексты состояний — describeProSubscription (app/utils/proPurchase.ts).
 *
 * Кнопка «Купить» у сотрудника без права выставлять счета заменяется
 * подписью: счёт на организацию запрашивает администратор или «Бухгалтерия».
 * Право — с сервера (useAppPermissions), по догадке кнопку не прячем.
 */
import { computed, watch } from 'vue'
import { formatPlanDate, PRO_ROUTE, proPriceText } from '~/utils/proPlan'
import {
  describeProSubscription,
  formatRub,
  PRO_REQUEST_STATUS_LABELS,
  todayIso,
} from '~/utils/proPurchase'

const router = useRouter()
const apiStore = useApiStore()
const { features } = usePortalFeatures()
const { request, loadCurrentRequest } = useProPurchase()
const { permissions } = useAppPermissions()

const subscription = computed(() => features.value?.billing || null)

watch(
  () => Boolean(features.value) && apiStore.hasToken,
  (ready) => {
    if (ready) {
      void loadCurrentRequest()
    }
  },
  { immediate: true }
)

const card = computed(() => describeProSubscription({
  subscription: subscription.value,
  request: request.value,
  today: todayIso(),
}))

const cannotBuy = computed(() => permissions.value.known && !permissions.value.billing_issue)

const TONE_CLASSES: Record<string, string> = {
  info: 'bg-[#e8f3ff] text-[#0058c2]',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-800',
  danger: 'bg-rose-50 text-rose-700',
  muted: 'bg-slate-100 text-slate-600',
}

const lastRequestText = computed(() => {
  const last = request.value
  if (!last) {
    return 'Заявок на счёт пока не было.'
  }

  return `Последняя заявка: ${last.invoiceNumber} от ${formatPlanDate(last.invoiceDate)}, `
    + `${last.monthsText}, ${formatRub(last.total)} — ${PRO_REQUEST_STATUS_LABELS[last.status].toLowerCase()}.`
})

const ROWS: Array<{ label: string, basic: boolean }> = [
  { label: 'Часы в карточке задачи, семь отчётов, выгрузки', basic: true },
  { label: 'Доска проектов, закрытие месяца, проверка данных', basic: true },
  { label: 'БДДС по проектам', basic: false },
  { label: 'Счета и акты из часов', basic: false },
  { label: 'Роли и права', basic: false },
]
</script>

<template>
  <B24Card>
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <span class="text-base font-semibold text-slate-900">Подписка</span>
          <span class="rounded-full px-2.5 py-0.5 text-[12px] font-semibold" :class="TONE_CLASSES[card.tone]">
            {{ card.badge }}
          </span>
        </div>
        <template v-if="card.action">
          <span v-if="cannotBuy && card.action !== 'Открыть счёт'" class="text-sm text-slate-500">
            Подключает администратор портала или «Бухгалтерия»
          </span>
          <B24Button v-else :label="card.action" color="primary" @click="router.push(PRO_ROUTE)" />
        </template>
      </div>
    </template>

    <p class="text-sm text-slate-700">{{ card.text }}</p>

    <div class="mt-4 overflow-x-auto">
      <table class="w-full min-w-[460px] border-collapse text-sm">
        <thead>
          <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            <th class="py-2 pr-3 font-semibold">Что умеет</th>
            <th class="w-[110px] py-2 text-center font-semibold">Базовый</th>
            <th class="w-[130px] py-2 text-center font-semibold">Pro</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ROWS" :key="row.label" class="border-b border-slate-100">
            <td class="py-2 pr-3 text-slate-700">{{ row.label }}</td>
            <td class="py-2 text-center" :class="row.basic ? 'text-emerald-600' : 'text-slate-400'">
              {{ row.basic ? '✓' : '—' }}
            </td>
            <td class="py-2 text-center text-emerald-600">✓</td>
          </tr>
          <tr>
            <td class="py-2 pr-3 font-semibold text-slate-900">Цена</td>
            <td class="py-2 text-center text-slate-600">без доплаты</td>
            <td class="py-2 text-center">
              <span class="font-semibold text-slate-900">{{ proPriceText(subscription?.priceMonthRub) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <template #footer>
      <p class="text-sm text-slate-500">{{ lastRequestText }}</p>
    </template>
  </B24Card>
</template>
