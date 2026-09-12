<script setup lang="ts">
/**
 * Общая страница платных функций раздела «Финансы».
 *
 * Страница ОДНА на все такие функции и различает их параметром маршрута
 * (/finance/bdds, /finance/billing). Отдельная заглушка на каждую функцию
 * означала бы копию одного и того же текста в двух местах, а расходятся такие
 * копии на первой же правке формулировки.
 *
 * ВАЖНО про «Счёт и акт». У него появился собственный экран
 * (app/pages/finance/billing/index.client.vue), и статический маршрут в Nuxt
 * приоритетнее динамического — то есть /finance/billing сюда больше не
 * попадает. Ветка для 'billing' здесь всё равно оставлена: она отрабатывает,
 * если экран когда-нибудь уберут, и она читает ТО ЖЕ состояние подписки с
 * сервера, что и сам экран, — двух разных ответов на вопрос «функция
 * включена?» в приложении быть не должно.
 *
 * Тексты — app/utils/paidFeatures.ts, разметка карточки —
 * app/components/finance/PaidFeatureCard.vue, аварийный выключатель —
 * FINANCE_* в app/utils/featureFlags.ts. Здесь ничего из этого не дублируем.
 */
import { computed } from 'vue'
import PaidFeatureCard from '~/components/finance/PaidFeatureCard.vue'
import { isPaidFeatureId, PAID_FEATURES } from '~/utils/paidFeatures'
import { FINANCE_BDDS_ENABLED } from '~/utils/featureFlags'

const route = useRoute()
const router = useRouter()

const { access: billingAccess } = useBillingFeature()

const featureId = computed(() => {
  const raw = Array.isArray(route.params.feature) ? route.params.feature[0] : route.params.feature

  return isPaidFeatureId(raw) ? raw : null
})

const isEnabled = computed(() => featureId.value === 'billing'
  ? billingAccess.value.enabled
  : FINANCE_BDDS_ENABLED)

const badge = computed(() => featureId.value === 'billing'
  ? billingAccess.value.badge
  : undefined)

useHead({
  title: computed(() => featureId.value
    ? `${PAID_FEATURES[featureId.value].label} — Финансы`
    : 'Финансы')
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      :title="featureId ? PAID_FEATURES[featureId].label : 'Финансы'"
      description="Раздел «Финансы»"
    >
      <template #links>
        <B24Button label="На главную" color="link" @click="router.push('/')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 space-y-6">
      <B24Empty
        v-if="!featureId"
        title="Такой функции в разделе «Финансы» нет."
        description="Проверьте адрес: раздел различает функции параметром — /finance/bdds или /finance/billing."
        size="sm"
      />

      <PaidFeatureCard
        v-else
        :feature-id="featureId"
        :enabled="isEnabled"
        :badge="badge"
      />
    </div>
  </B24Container>
</template>
