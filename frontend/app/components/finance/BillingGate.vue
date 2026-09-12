<script setup lang="ts">
/**
 * Общая обвязка экранов «Счёта и акта»: шапка и три состояния входа.
 *
 * Состояний ровно три, и они одинаковы на всех трёх экранах функции (мастер,
 * реестр, карточка), поэтому живут здесь, а не копией в каждой странице:
 *
 *  1. подписку ещё не спросили (/api/features в полёте) — «проверяем»;
 *  2. функция выключена или сервер о ней не ответил — та же заглушка с
 *     замком, что и до появления экрана (PaidFeatureCard);
 *  3. функция открыта — содержимое экрана. Если тариф Pro закончился
 *     («только чтение»), идёт грейс или кончается пробный период, над
 *     содержимым плашка ProPlanNotice; кнопки создания и изменения экраны
 *     прячут сами по access.canWrite.
 *
 * Второе состояние — главное требование задачи: при state = off пункт меню
 * остаётся с замком и ведёт на заглушку. Прямой переход по адресу
 * /finance/billing тоже обязан упереться в неё, а не в рабочий мастер: адрес
 * знать несложно, а подписка — не секрет, который стоит охранять вёрсткой.
 * Настоящая защита всё равно на сервере (контракт, правило 2).
 *
 * Шапка здесь своя, а не ReportShell: у того в шапке жёстко сидят фильтр
 * отчёта (сотрудники и проекты), свежесть данных, «Excel» и «Сформировать» —
 * ни одно из этих полей «Счёту и акту» не подходит.
 */
import { computed } from 'vue'
import PaidFeatureCard from '~/components/finance/PaidFeatureCard.vue'
import ProPlanNotice from '~/components/finance/ProPlanNotice.vue'

defineProps<{
  title: string
  description?: string
}>()

const { access, features, featuresFailed } = useBillingFeature()

const priceMonthRub = computed(() => features.value?.billing?.priceMonthRub ?? null)
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame flex flex-col gap-4">
      <section class="ms-surface flex flex-col gap-3 p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h1 class="text-xl font-semibold tracking-tight text-slate-900">{{ title }}</h1>
              <span
                v-if="access.badge"
                class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
                :class="access.locked || access.readOnly ? 'bg-[#0075ff] text-white' : 'bg-slate-100 text-slate-500'"
              >
                {{ access.badge }}
              </span>
            </div>
            <p v-if="description" class="mt-1 text-sm text-slate-500">{{ description }}</p>
          </div>

          <div v-if="access.enabled" class="flex flex-wrap items-center justify-end gap-2">
            <slot name="actions" />
          </div>
        </div>

        <slot v-if="access.enabled" name="filters" />
      </section>

      <div v-if="access.unknown && !featuresFailed" class="ms-surface ms-empty-state">
        Проверяем подписку…
      </div>

      <PaidFeatureCard
        v-else-if="access.locked"
        feature-id="billing"
        :enabled="false"
        :badge="access.badge"
        :price-month-rub="priceMonthRub"
      >
        <template #footer>
          <p v-if="featuresFailed" class="mt-3 text-sm text-amber-700">
            Состояние подписки узнать не удалось — сервер не ответил на запрос о платных функциях.
            Экран останется закрытым, пока ответ не придёт: обновите страницу позже.
          </p>
        </template>
      </PaidFeatureCard>

      <template v-else>
        <ProPlanNotice :notice="access.notice" feature-id="billing" />
        <slot />
      </template>
    </div>
  </div>
</template>
