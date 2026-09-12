<script setup lang="ts">
/**
 * Бюджет проекта: показатели, прогноз, последние операции.
 *
 * В макете это ЧЕТВЁРТАЯ ВКЛАДКА карточки проекта, и так и будет: карточка
 * проекта живёт в дровере доски (components/projects/ProjectBoardDrawer.vue)
 * и открывается поверх доски, а не отдельным адресом. Отдельная страница
 * нужна независимо от вкладки, и вот зачем:
 *  - на неё ведёт ссылка из уведомления о риске и перерасходе (её строит
 *    project_budget_notifier), а уведомление обязано открывать конкретный
 *    проект, а не доску;
 *  - по ней открывается проект из реестра, и адрес можно переслать.
 *
 * Вкладка в дровере на этап 1 не добавлена сознательно: там четыре вкладки
 * уже про карточку проекта, а пятая со своим запросом к серверу — это
 * правка общего для доски компонента, которую сейчас параллельно правит
 * другая задача. Ссылка «Бюджет проекта» из панели реестра эту работу
 * закрывает, а вкладка встанет на этап 2, когда появятся статьи и её
 * содержимое перестанет повторять этот экран.
 *
 * Расчётов в компоненте нет: всё в app/utils/bddsRegistry.ts.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import BddsGate from '~/components/finance/BddsGate.vue'
import { describeBddsError, type BddsErrorView } from '~/utils/bddsErrors'
import {
  BDDS_FORECAST_METHOD_HINT,
  bddsBarPercent,
  bddsProjectSubtitle,
  bddsStatusTone,
  describeBddsForecast,
  describeBddsNoBudget,
  describeBddsRateGap,
  formatBddsRemaining,
  type BddsStatusTone,
} from '~/utils/bddsRegistry'
import {
  formatProjectCurrency,
  formatProjectDate,
  formatProjectHours,
  formatProjectPercent,
  getBudgetStatusBadgeClass,
} from '~/utils/projectBoard'
import { buildBoardUtilization, formatBoardActivity } from '~/utils/projectBoardView'
import type { BddsProjectRecord } from '~/types/bdds'

const route = useRoute()
const router = useRouter()
const apiStore = useApiStore()
const { access } = useBddsFeature()

const { initApp, processErrorGlobal } = useAppInit('BddsProjectPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const TONE_TEXT: Record<BddsStatusTone, string> = {
  ok: 'text-emerald-700',
  warning: 'text-amber-700',
  danger: 'text-rose-700',
  neutral: 'text-slate-700',
}

const TONE_BAR: Record<BddsStatusTone, string> = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
  neutral: 'bg-slate-300',
}

const isReady = ref(false)
const isLoading = ref(false)
const error = ref<BddsErrorView | null>(null)
const project = ref<BddsProjectRecord | null>(null)

const projectId = computed(() => {
  const raw = Array.isArray(route.params.projectId) ? route.params.projectId[0] : route.params.projectId
  return String(raw || '').trim()
})

async function loadProject() {
  if (!access.value.enabled || !projectId.value) {
    return
  }

  isLoading.value = true
  error.value = null

  try {
    const response = await apiStore.getBddsProject(projectId.value)
    project.value = response.project
  } catch (e) {
    error.value = describeBddsError(e)
    project.value = null
  } finally {
    isLoading.value = false
  }
}

const forecast = computed(() => project.value ? describeBddsForecast(project.value) : null)
const rateGap = computed(() => project.value ? describeBddsRateGap(project.value) : null)
const utilization = computed(() => project.value ? buildBoardUtilization(project.value) : null)

/** Шесть показателей, как в макете. Тексты — здесь, расчёты — на сервере. */
const kpis = computed(() => {
  const row = project.value
  if (!row) {
    return []
  }

  return [
    {
      id: 'plan',
      label: 'Бюджет проекта, ₽',
      value: row.has_budget ? formatProjectCurrency(row.planned_amount) : 'без лимита',
      hint: row.has_budget
        ? `освоено ${formatProjectPercent(row.budget_utilization_percent)}`
        : describeBddsNoBudget(row),
      tone: 'neutral' as BddsStatusTone,
      source: 'расчёт',
    },
    {
      id: 'fact',
      label: 'Факт выбытий, ₽',
      value: formatProjectCurrency(row.actual_cost_amount),
      hint: `остаток ${formatBddsRemaining(row)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'списания',
    },
    {
      id: 'hours',
      label: 'Часы',
      value: formatProjectHours(row.actual_hours),
      hint: row.planned_hours === null
        ? 'без лимита'
        : `план ${formatProjectHours(row.planned_hours)} · остаток ${formatProjectHours(row.hours_remaining)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'списания',
    },
    {
      id: 'income',
      label: 'Поступления, ₽',
      value: formatProjectCurrency(row.actual_income_amount),
      hint: `внешние платежи ${formatProjectCurrency(row.actual_expense_amount)}`,
      tone: 'neutral' as BddsStatusTone,
      source: 'операции',
    },
    {
      id: 'financial-result',
      label: 'Финрезультат, ₽',
      value: formatProjectCurrency(row.actual_financial_result),
      hint: row.actual_financial_result < 0 ? 'минус' : 'плюс',
      tone: (row.actual_financial_result < 0 ? 'danger' : 'ok') as BddsStatusTone,
      source: 'операции',
    },
    {
      id: 'forecast',
      label: 'Прогноз выбытий, ₽',
      value: forecast.value?.value || '—',
      hint: forecast.value?.deviation || forecast.value?.explanation || '',
      tone: forecast.value?.tone || ('neutral' as BddsStatusTone),
      source: 'расчёт',
    },
  ]
})

const operations = computed(() => project.value?.recent_finance_operations || [])

useHead({
  title: computed(() => project.value
    ? `${project.value.project_name} — бюджет проекта`
    : 'Бюджет проекта'),
})

watch(() => access.value.enabled, (enabled) => {
  if (enabled && isReady.value) {
    void loadProject()
  }
})

/** Смена проекта в адресе — новая загрузка: страница одна на все проекты. */
watch(projectId, () => {
  if (isReady.value) {
    void loadProject()
  }
})

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    isReady.value = true
  } catch (e) {
    processErrorGlobal(e)
    return
  }

  await loadProject()
})
</script>

<template>
  <BddsGate
    :title="project?.project_name || 'Бюджет проекта'"
    :description="project ? bddsProjectSubtitle(project) : 'Показатели бюджета одного проекта'"
  >
    <template #actions>
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadProject" />
      <B24Button label="К реестру" color="link" @click="router.push('/finance/bdds')" />
    </template>

    <div v-if="error" class="ms-note ms-note-danger">
      <p class="font-medium">{{ error.title }}</p>
      <p v-if="error.hint" class="mt-1 text-sm">{{ error.hint }}</p>
    </div>

    <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>

    <template v-else-if="project">
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="kpi in kpis" :key="kpi.id" class="ms-surface flex flex-col gap-1 p-4">
          <div class="flex items-center gap-2 text-xs text-slate-500">
            <span>{{ kpi.label }}</span>
            <span class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
              {{ kpi.source }}
            </span>
          </div>
          <div class="text-xl font-semibold" :class="TONE_TEXT[kpi.tone]">{{ kpi.value }}</div>
          <div class="text-xs text-slate-500">{{ kpi.hint }}</div>
        </div>
      </section>

      <section class="ms-surface flex flex-col gap-3 p-5">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium"
            :class="getBudgetStatusBadgeClass(project.budget_health_status)"
          >
            {{ project.budget_health_status }}
          </span>
          <span v-if="project.is_support" class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            поддержка
          </span>
          <span class="text-xs text-slate-500">{{ project.budget_health_reason }}</span>
        </div>

        <div v-if="project.has_budget && utilization">
          <div class="flex items-center gap-2">
            <span class="h-2 grow overflow-hidden rounded-full bg-slate-100">
              <span
                class="block h-full rounded-full"
                :class="TONE_BAR[bddsStatusTone(project.budget_health_status)]"
                :style="{ width: `${bddsBarPercent(project.budget_utilization_percent)}%` }"
              />
            </span>
            <span class="text-sm text-slate-600">
              {{ formatProjectPercent(project.budget_utilization_percent) }}
            </span>
          </div>
          <p class="mt-1 text-xs text-slate-500">{{ utilization.label }}</p>
        </div>
        <p v-else class="ms-note ms-note-info text-sm">{{ describeBddsNoBudget(project) }}</p>

        <p v-if="rateGap" class="ms-note text-sm">{{ rateGap }}</p>

        <dl class="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt class="text-xs text-slate-500">Срок проекта</dt>
            <dd class="text-slate-900">
              {{ formatProjectDate(project.project_start_date) }} — {{ formatProjectDate(project.project_end_date) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-slate-500">Куратор</dt>
            <dd class="text-slate-900">{{ project.curator_name || 'Не задан' }}</dd>
          </div>
          <div>
            <dt class="text-xs text-slate-500">Последнее списание</dt>
            <dd class="text-slate-900">{{ formatBoardActivity(project) }}</dd>
          </div>
        </dl>

        <p class="text-xs text-slate-400">{{ BDDS_FORECAST_METHOD_HINT }}</p>
      </section>

      <section class="ms-surface flex flex-col gap-3 p-5">
        <h2 class="text-base font-semibold text-slate-900">Последние операции смарт-процесса</h2>

        <p v-if="!operations.length" class="text-sm text-slate-500">
          Операций по этому проекту не видно. Поступления и внешние платежи ведутся в смарт-процессе
          «Доходы-расходы (App)» на портале; если он не настроен, план и факт по часам всё равно считаются.
        </p>

        <div v-else class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Тип</th>
                <th class="text-right">Сумма</th>
                <th>Источник</th>
                <th>Комментарий</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(operation, index) in operations" :key="operation.id || index">
                <td>{{ formatProjectDate(operation.operation_date) }}</td>
                <td>{{ operation.operation_type === 'income' ? 'Поступление' : 'Выбытие' }}</td>
                <td
                  class="text-right"
                  :class="operation.operation_type === 'income' ? 'text-emerald-700' : 'text-rose-700'"
                >
                  {{ formatProjectCurrency(operation.amount) }}
                </td>
                <td>{{ operation.source || '—' }}</td>
                <td>{{ operation.comment || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-else-if="!error" class="ms-surface ms-empty-state">
      Проект не выбран. Откройте его из реестра «БДДС по проектам».
    </div>
  </BddsGate>
</template>
