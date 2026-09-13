<script setup lang="ts">
/**
 * «Суммы вам не видны» — третье состояние экранов денег рядом с «проверяем
 * подписку» и замком (BddsGate.vue, BillingGate.vue).
 *
 * Появляется только при подключённой ролевой модели и только когда сервер
 * сказал, что права money_view у человека нет: без ролей суммы видят все, и
 * пугать отказом, которого не будет, нельзя. Настоящая охрана — на сервере
 * (@permission_required('money_view')); здесь забота о человеке: вместо
 * плашки с машинным 403 — объяснение, какие роли видят суммы и где их
 * назначают.
 */
import { describeMoneyAccessDenied, ROLES_SETTINGS_PATH } from '~/utils/appRoles'

const router = useRouter()
const { me } = useAppPermissions()
</script>

<template>
  <section class="ms-surface flex flex-col gap-3 p-5">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-base font-semibold text-slate-900">Суммы вам не видны</span>
      <span
        v-if="me"
        class="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
      >
        ваша роль: {{ me.roleTitle }}
      </span>
    </div>
    <p class="text-sm text-slate-600">{{ describeMoneyAccessDenied() }}</p>
    <div>
      <B24Button label="Посмотреть роли и права" color="link" @click="router.push(ROLES_SETTINGS_PATH)" />
    </div>
  </section>
</template>
