<script setup lang="ts">
/**
 * Плашка тарифа над открытым экраном платной функции.
 *
 * Появляется, когда функция открыта, но не «как обычно»:
 *  - Pro закончился — «только просмотр»: что закрыто и что осталось;
 *  - грейс после оплаты — до какого числа всё работает;
 *  - последние дни пробного периода.
 * В остальное время компонент ничего не рисует. Тексты считает
 * resolveFeatureAccess (app/utils/featureAccess.ts).
 */
import type { PlanNotice } from '~/utils/featureAccess'
import { PRO_CTA_LABEL, proRoute } from '~/utils/proPlan'

const props = defineProps<{
  notice: PlanNotice | null
  featureId: string
}>()

const router = useRouter()

function openPro() {
  void router.push(proRoute(props.featureId))
}
</script>

<template>
  <div
    v-if="notice"
    class="ms-note flex flex-wrap items-center justify-between gap-3"
    :class="notice.tone === 'danger' ? 'ms-note-danger' : 'border-amber-200 bg-amber-50 text-amber-800'"
    role="status"
  >
    <div class="min-w-0">
      <p class="font-semibold">{{ notice.title }}</p>
      <p class="mt-1">{{ notice.text }}</p>
    </div>
    <B24Button :label="PRO_CTA_LABEL" color="primary" size="sm" @click="openPro" />
  </div>
</template>
