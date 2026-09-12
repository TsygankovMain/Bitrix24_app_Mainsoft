<script setup lang="ts">
/**
 * «Подключить Pro» — точка, куда ведут все замки платных функций.
 *
 * Пока это заглушка: формы запроса счёта нет, её сделают после HTML-макета.
 * Когда форма появится, она встанет ЗДЕСЬ — все кнопки уже ведут на этот
 * адрес (PRO_ROUTE в app/utils/proPlan.ts), менять их не придётся.
 *
 * ?feature=<код> — с какой функции человек пришёл: заглушке он нужен, чтобы
 * вернуть назад, форме — чтобы знать, что хотели подключить.
 */
import { computed } from 'vue'
import { isFinanceFeatureId, isPaidFeatureId, paidFeatureRoute, PAID_FEATURES } from '~/utils/paidFeatures'
import { PRO_CONTACT_EMAIL, PRO_PLAN_LABEL, PRO_STUB_TEXT, proPriceText } from '~/utils/proPlan'

useHead({ title: `Тариф ${PRO_PLAN_LABEL}` })

const route = useRoute()
const router = useRouter()
const { features } = usePortalFeatures()

const featureId = computed(() => {
  const raw = Array.isArray(route.query.feature) ? route.query.feature[0] : route.query.feature

  return isPaidFeatureId(raw) ? raw : null
})

const priceText = computed(() => {
  const price = Object.values(features.value || {})[0]?.priceMonthRub

  return proPriceText(price)
})

const includedFeatures = computed(() => [PAID_FEATURES.bdds, PAID_FEATURES.billing, PAID_FEATURES.roles])

function goBack() {
  const id = featureId.value
  void router.push(id && isFinanceFeatureId(id) ? paidFeatureRoute(id) : '/')
}
</script>

<template>
  <B24Container>
    <B24PageHeader :title="`Тариф ${PRO_PLAN_LABEL}`" :description="priceText">
      <template #links>
        <B24Button label="Назад" color="link" @click="goBack" />
      </template>
    </B24PageHeader>

    <div class="mt-6 flex flex-col gap-4">
      <div class="ms-note ms-note-info" role="status">
        <p class="font-semibold">{{ PRO_STUB_TEXT }}</p>
        <p class="mt-1">
          Адрес для связи:
          <a :href="`mailto:${PRO_CONTACT_EMAIL}`" class="font-semibold underline">{{ PRO_CONTACT_EMAIL }}</a>.
          Укажите адрес портала — тариф подключается на портал целиком, для всех сотрудников.
        </p>
      </div>

      <B24Card>
        <template #header>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold text-slate-900">Что входит в {{ PRO_PLAN_LABEL }}</span>
            <span class="rounded-full bg-[#0075ff] px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
              {{ PRO_PLAN_LABEL }}
            </span>
          </div>
        </template>

        <ul class="flex flex-col gap-3">
          <li
            v-for="feature in includedFeatures"
            :key="feature.id"
            class="flex flex-col gap-0.5"
            :class="feature.id === featureId ? 'rounded-lg bg-blue-50/60 px-3 py-2' : ''"
          >
            <span class="text-sm font-semibold text-slate-900">{{ feature.label }}</span>
            <span class="text-sm text-slate-600">{{ feature.benefit }}</span>
          </li>
        </ul>

        <template #footer>
          <p class="text-sm text-slate-500">
            Если тариф закончится, создание и изменение в этих функциях закроются, а просмотр и выгрузки останутся:
            данные портала остаются его данными.
          </p>
        </template>
      </B24Card>
    </div>
  </B24Container>
</template>
