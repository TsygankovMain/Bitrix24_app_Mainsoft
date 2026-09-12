<script setup lang="ts">
/**
 * Отказ сервера плашкой, а не фатальным экраном.
 *
 * Экраны «Счёта и акта» намеренно не зовут processErrorGlobal на каждую
 * ошибку: app/error.vue рендерится без пути лёгкого возврата (:clear="false"),
 * единственный выход — перезагрузка. Для «эти часы уже выставлены» (штатный
 * 409 с ссылкой на готовый документ) или «нет шаблона акта» это
 * непропорционально: человеку нужна ссылка и объяснение, а не белый экран.
 *
 * Разбор ошибки — describeBillingError в app/utils/billingErrors.ts, здесь
 * только показ. Ссылка на существующий документ рисуется, когда сервер
 * прислал его идентификатор: это и есть требование контракта об
 * идемпотентности (правило 8) в переводе на язык интерфейса.
 */
import type { BillingErrorView } from '~/utils/billingErrors'

defineProps<{
  error: BillingErrorView | null
}>()

const router = useRouter()
</script>

<template>
  <div v-if="error" class="ms-note ms-note-danger">
    <p class="font-semibold">{{ error.title }}</p>
    <p class="mt-1">{{ error.text }}</p>
    <div v-if="error.documentId" class="mt-3">
      <B24Button
        label="Открыть документ"
        color="primary"
        size="sm"
        @click="router.push(`/finance/billing/${error.documentId}`)"
      />
    </div>
  </div>
</template>
