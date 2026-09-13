<script setup lang="ts">
/**
 * Подвал раскрытых «Финансов»: цена Pro и кнопка (макет, экран 1.1).
 *
 * Цена называется сразу — чтобы администратор не шёл выяснять, сколько
 * стоит. При действующем Pro подвала нет.
 */
import { computed } from 'vue'
import { PRO_CTA_LABEL, PRO_ROUTE, proPriceText } from '~/utils/proPlan'
import { shouldShowFinanceProFooter } from '~/utils/proPurchase'

const emit = defineEmits<{ navigate: [] }>()

const router = useRouter()
const { features } = usePortalFeatures()

const subscription = computed(() => features.value?.billing || null)
const visible = computed(() => shouldShowFinanceProFooter(subscription.value))

function openPro() {
  emit('navigate')
  void router.push(PRO_ROUTE)
}
</script>

<template>
  <div
    v-if="visible"
    class="mt-1 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-3 pb-1 pt-3"
  >
    <p class="min-w-0 text-xs text-slate-500">
      <span class="block text-sm font-semibold text-slate-900">Pro: {{ proPriceText(subscription?.priceMonthRub) }}.</span>
      БДДС, счета и акты, роли и права.
    </p>
    <B24Button :label="PRO_CTA_LABEL" color="primary" size="sm" @click="openPro" />
  </div>
</template>
