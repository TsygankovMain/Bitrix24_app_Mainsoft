<script setup lang="ts">
/**
 * Общая страница платных функций раздела «Финансы».
 *
 * Страница ОДНА на все такие функции и различает их параметром маршрута
 * (/finance/bdds, /finance/billing). Отдельная заглушка на каждую функцию
 * означала бы копию одного и того же текста в двух местах, а расходятся такие
 * копии на первой же правке формулировки.
 *
 * Тексты — app/utils/paidFeatures.ts, состояние — FINANCE_* в
 * app/utils/featureFlags.ts. Здесь ни того, ни другого не дублируем.
 */
import { computed } from 'vue'
import LockIcon from '@bitrix24/b24icons-vue/main/LockIcon'
import { isPaidFeatureId, resolvePaidFeatureState } from '~/utils/paidFeatures'
import { FINANCE_BDDS_ENABLED, FINANCE_BILLING_ENABLED } from '~/utils/featureFlags'

const route = useRoute()
const router = useRouter()

const featureId = computed(() => {
  const raw = Array.isArray(route.params.feature) ? route.params.feature[0] : route.params.feature

  return isPaidFeatureId(raw) ? raw : null
})

const state = computed(() => {
  const id = featureId.value

  if (!id) {
    return null
  }

  return resolvePaidFeatureState(
    id,
    id === 'bdds' ? FINANCE_BDDS_ENABLED : FINANCE_BILLING_ENABLED
  )
})

useHead({
  title: computed(() => state.value ? `${state.value.feature.label} — Финансы` : 'Финансы')
})
</script>

<template>
  <B24Container>
    <B24PageHeader
      :title="state?.feature.label || 'Финансы'"
      description="Раздел «Финансы»"
    >
      <template #links>
        <B24Button label="На главную" color="link" @click="router.push('/')" />
      </template>
    </B24PageHeader>

    <div class="mt-6 space-y-6">
      <B24Empty
        v-if="!state"
        title="Такой функции в разделе «Финансы» нет."
        description="Проверьте адрес: раздел различает функции параметром — /finance/bdds или /finance/billing."
        size="sm"
      />

      <template v-else>
        <B24Card>
          <template #header>
            <div class="flex flex-wrap items-center gap-2">
              <LockIcon v-if="state.locked" class="size-5 text-slate-400" aria-hidden="true" />
              <span class="text-base font-semibold text-slate-900">{{ state.feature.label }}</span>
              <span
                v-if="state.badge"
                class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
              >
                {{ state.badge }}
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
            <p v-if="state.hint" class="text-sm text-slate-500">{{ state.hint }}</p>
            <p v-else class="text-sm text-slate-500">
              Функция подключена. Экран появится в этом разделе.
            </p>
          </template>
        </B24Card>
      </template>
    </div>
  </B24Container>
</template>
