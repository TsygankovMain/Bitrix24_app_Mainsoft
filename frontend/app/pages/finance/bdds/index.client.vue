<script setup lang="ts">
/**
 * Реестр проектов с бюджетами — точка входа функции «БДДС по проектам».
 *
 * Пункт меню «Финансы → БДДС по проектам» ведёт на /finance/bdds, и
 * статический маршрут в Nuxt приоритетнее динамического /finance/[feature] —
 * то есть при включённой подписке человек попадает сюда, а при выключенной
 * BddsGate показывает ровно ту заглушку с замком, что была на этом адресе
 * раньше.
 *
 * ТРЕТЬЕГО списка проектов здесь не появляется. Строка реестра — та же
 * карточка проекта, что на доске, и рисуют её те же утилиты
 * (buildBoardUtilization, matchesBoardSearch, formatBoardActivity). Своё
 * здесь только то, чего на доске нет: прогноз, чипы по статусу бюджета и
 * итог по портфелю. Все расчёты и тексты — в app/utils/bddsRegistry.ts,
 * компонент только рисует.
 *
 * Чего на этом экране НЕТ и почему: статей ДДС, плана по месяцам и колонки
 * «в ожидании». Это этап 2, он ждёт ответов пользователя (записка к макету,
 * вопросы 1, 2, 7, 8). Пустая колонка «в ожидании» читалась бы как «денег в
 * пути нет», а это не то же самое, что «мы этого ещё не считаем».
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
  buildBddsChips,
  buildBddsKpis,
  countActiveBddsFilters,
  describeBddsForecast,
  describeBddsNoBudget,
  describeBddsRateGap,
  filterBddsProjects,
  formatBddsPlan,
  formatBddsRemaining,
  DEFAULT_BDDS_FILTERS,
  type BddsFilterState,
  type BddsStatusFilterId,
  type BddsStatusTone,
} from '~/utils/bddsRegistry'
import { formatProjectCurrency, formatProjectHours, formatProjectPercent, getBudgetStatusBadgeClass } from '~/utils/projectBoard'
import { buildBoardUtilization, formatBoardActivity } from '~/utils/projectBoardView'
import type { BddsProjectRecord, BddsThresholds, BddsTotals } from '~/types/bdds'

const router = useRouter()
const apiStore = useApiStore()
const { access } = useBddsFeature()

useHead({ title: 'БДДС по проектам' })

const { initApp, processErrorGlobal } = useAppInit('BddsRegistryPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
let $b24: null | B24Frame = null

const isReady = ref(false)
const isLoading = ref(false)
const error = ref<BddsErrorView | null>(null)
const projects = ref<BddsProjectRecord[]>([])
const totals = ref<BddsTotals | null>(null)
const statusCounts = ref<Record<string, number>>({})
const thresholds = ref<BddsThresholds | null>(null)
const filters = ref<BddsFilterState>({ ...DEFAULT_BDDS_FILTERS })
const selectedProjectId = ref('')

/** Цветовая зона -> классы. Один словарь на всю страницу, чтобы не разъезжались. */
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

async function loadProjects() {
  if (!access.value.enabled) {
    return
  }

  isLoading.value = true
  error.value = null

  try {
    const response = await apiStore.getBddsProjects()
    projects.value = response.projects || []
    totals.value = response.totals || null
    statusCounts.value = response.status_counts || {}
    thresholds.value = response.thresholds || null

    // Выбранный проект мог уйти из выборки (архив, переименование) —
    // держать его в панели значило бы показывать цифры от прошлой загрузки.
    if (!projects.value.some(row => row.project_id === selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.project_id || ''
    }
  } catch (e) {
    error.value = describeBddsError(e)
    projects.value = []
    totals.value = null
    statusCounts.value = {}
  } finally {
    isLoading.value = false
  }
}

const chips = computed(() => buildBddsChips(projects.value))

/**
 * Строки таблицы с уже посчитанными прогнозом и полосой освоения.
 *
 * Считаем ОДИН раз на строку, а не в шаблоне: describeBddsForecast в трёх
 * ячейках подряд — это три одинаковых вызова на каждую перерисовку и три
 * места, где текст может разойтись.
 */
const visibleRows = computed(() => filterBddsProjects(projects.value, filters.value).map(row => ({
  row,
  forecast: describeBddsForecast(row),
  utilization: buildBoardUtilization(row),
})))

const visibleProjects = computed(() => visibleRows.value.map(item => item.row))
const activeFilters = computed(() => countActiveBddsFilters(filters.value))
const kpis = computed(() => (totals.value && thresholds.value)
  ? buildBddsKpis(totals.value, statusCounts.value, thresholds.value)
  : [])

const selectedProject = computed(() => visibleProjects.value.find(
  row => row.project_id === selectedProjectId.value
) || visibleProjects.value[0] || null)

const selectedForecast = computed(() => selectedProject.value
  ? describeBddsForecast(selectedProject.value)
  : null)

const selectedRateGap = computed(() => selectedProject.value
  ? describeBddsRateGap(selectedProject.value)
  : null)

function selectChip(id: BddsStatusFilterId) {
  filters.value = { ...filters.value, status: id }
}

function resetFilters() {
  filters.value = { ...DEFAULT_BDDS_FILTERS }
}

function openProject(projectId: string) {
  const id = String(projectId || '').trim()
  if (!id) {
    return
  }

  void router.push(`/finance/bdds/${encodeURIComponent(id)}`)
}

/**
 * Загрузка ждёт ответа о подписке.
 *
 * Спрашивать реестр раньше, чем известно состояние функции, значит
 * гарантированно получить 403 на выключенном портале и показать плашку
 * отказа там, где нужна заглушка с замком.
 */
watch(() => access.value.enabled, (enabled) => {
  if (enabled && isReady.value) {
    void loadProjects()
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

  await loadProjects()
})
</script>

<template>
  <BddsGate
    title="БДДС по проектам"
    description="Бюджет движения денежных средств в разрезе проекта. Факт затрат — из списаний часов по ставке на момент списания, поступления и внешние платежи — из операций смарт-процесса."
  >
    <template #actions>
      <B24Button label="Обновить" color="default" :loading="isLoading" @click="loadProjects" />
      <B24Button label="Проекты" color="link" @click="router.push('/projects')" />
    </template>

    <template #filters>
      <div class="flex flex-wrap items-end gap-4">
        <div class="min-w-[240px] grow">
          <label class="mb-2 block text-sm font-medium text-slate-700" for="bdds-search">Поиск</label>
          <input
            id="bdds-search"
            v-model="filters.query"
            type="search"
            class="w-full"
            placeholder="Проект, клиент, куратор…"
          >
        </div>

        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input v-model="filters.onlyWithBudget" type="checkbox">
          Только с лимитом
        </label>

        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input v-model="filters.onlyForecastOverrun" type="checkbox">
          Прогноз выходит за план
        </label>

        <B24Button
          v-if="activeFilters > 0"
          :label="`Сбросить (${activeFilters})`"
          color="link"
          @click="resetFilters"
        />
      </div>
    </template>

    <div v-if="error" class="ms-note ms-note-danger">
      <p class="font-medium">{{ error.title }}</p>
      <p v-if="error.hint" class="mt-1 text-sm">{{ error.hint }}</p>
    </div>

    <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>

    <template v-else-if="!error">
      <section v-if="kpis.length" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
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

      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="chip in chips"
          :key="chip.id"
          type="button"
          class="rounded-full border px-3 py-1 text-sm transition"
          :class="filters.status === chip.id
            ? 'border-[#0075ff] bg-blue-50 text-[#0075ff]'
            : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'"
          @click="selectChip(chip.id)"
        >
          {{ chip.label }}
          <span class="ml-1 text-xs text-slate-400">{{ chip.count }}</span>
        </button>
        <span class="ml-auto text-xs text-slate-400">{{ BDDS_FORECAST_METHOD_HINT }}</span>
      </div>

      <div v-if="!visibleRows.length" class="ms-surface ms-empty-state">
        Проектов по этому отбору нет.
        <template v-if="activeFilters > 0">Сбросьте фильтры, чтобы увидеть весь портфель.</template>
      </div>

      <div v-else class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th class="min-w-[220px]">Проект</th>
                <th class="text-right">План</th>
                <th class="text-right">Факт</th>
                <th class="text-right">Остаток</th>
                <th class="text-right">Прогноз</th>
                <th class="min-w-[140px]">Освоение</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="{ row, forecast, utilization } in visibleRows"
                :key="row.project_id"
                class="cursor-pointer"
                :class="row.project_id === selectedProject?.project_id ? 'bg-blue-50/40' : ''"
                @click="selectedProjectId = row.project_id"
                @dblclick="openProject(row.project_id)"
              >
                <td>
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-slate-900">{{ row.project_name }}</span>
                    <span
                      v-if="row.is_support"
                      class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500"
                    >поддержка</span>
                  </div>
                  <div class="text-xs text-slate-500">{{ bddsProjectSubtitle(row) }}</div>
                </td>
                <td class="text-right">{{ formatBddsPlan(row) }}</td>
                <td class="text-right">{{ formatProjectCurrency(row.actual_cost_amount) }}</td>
                <td
                  class="text-right"
                  :class="(row.budget_remaining ?? 0) < 0 ? 'text-rose-700' : ''"
                >
                  {{ formatBddsRemaining(row) }}
                </td>
                <td class="text-right" :title="forecast.explanation">
                  <div>{{ forecast.value }}</div>
                  <div v-if="forecast.deviation" class="text-xs" :class="TONE_TEXT[forecast.tone]">
                    {{ forecast.deviation }}
                  </div>
                </td>
                <td>
                  <template v-if="row.has_budget">
                    <div class="flex items-center gap-2">
                      <span class="h-1.5 grow overflow-hidden rounded-full bg-slate-100">
                        <span
                          class="block h-full rounded-full"
                          :class="TONE_BAR[bddsStatusTone(row.budget_health_status)]"
                          :style="{ width: `${bddsBarPercent(row.budget_utilization_percent)}%` }"
                        />
                      </span>
                      <span class="text-xs text-slate-500">
                        {{ formatProjectPercent(row.budget_utilization_percent) }}
                      </span>
                    </div>
                    <div class="mt-1 text-xs text-slate-400">{{ utilization.label }}</div>
                  </template>
                  <template v-else>
                    <div class="text-xs text-slate-500">
                      Финрезультат {{ formatProjectCurrency(row.actual_financial_result) }}
                    </div>
                    <div class="text-xs text-slate-400">{{ formatProjectHours(row.actual_hours) }} без лимита</div>
                  </template>
                </td>
                <td>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-medium"
                    :class="getBudgetStatusBadgeClass(row.budget_health_status)"
                  >
                    {{ row.budget_health_status }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
            Итог плана — только по проектам с заданным лимитом. Поддержка без лимита в него не входит:
            у неё контролируется финансовый результат, а не освоение.
          </p>
        </div>

        <aside v-if="selectedProject" class="ms-surface flex flex-col gap-3 p-4">
          <div>
            <h2 class="text-base font-semibold text-slate-900">{{ selectedProject.project_name }}</h2>
            <p class="text-xs text-slate-500">{{ bddsProjectSubtitle(selectedProject) }}</p>
          </div>

          <div class="flex flex-wrap gap-2">
            <span
              class="rounded-full px-2 py-0.5 text-xs font-medium"
              :class="getBudgetStatusBadgeClass(selectedProject.budget_health_status)"
            >
              {{ selectedProject.budget_health_status }}
            </span>
            <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              {{ selectedProject.is_support ? 'поддержка' : 'проект' }}
            </span>
            <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              ставка {{ formatProjectCurrency(selectedProject.hourly_rate) }}/ч
            </span>
          </div>

          <dl class="grid grid-cols-2 gap-2 text-sm">
            <div>
              <dt class="text-xs text-slate-500">План, ₽</dt>
              <dd class="font-medium text-slate-900">
                {{ selectedProject.has_budget ? formatProjectCurrency(selectedProject.planned_amount) : 'без лимита' }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-slate-500">Факт, ₽</dt>
              <dd class="font-medium text-slate-900">{{ formatProjectCurrency(selectedProject.actual_cost_amount) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-slate-500">План, ч</dt>
              <dd class="font-medium text-slate-900">
                {{ selectedProject.planned_hours === null ? 'без лимита' : formatProjectHours(selectedProject.planned_hours) }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-slate-500">Факт, ч</dt>
              <dd class="font-medium text-slate-900">{{ formatProjectHours(selectedProject.actual_hours) }}</dd>
            </div>
          </dl>

          <div class="rounded-lg bg-slate-50 p-3">
            <div class="text-xs text-slate-500">Финансовый результат по факту</div>
            <div
              class="text-lg font-semibold"
              :class="selectedProject.actual_financial_result < 0 ? 'text-rose-700' : 'text-emerald-700'"
            >
              {{ formatProjectCurrency(selectedProject.actual_financial_result) }}
            </div>
            <div class="text-xs text-slate-500">
              поступления {{ formatProjectCurrency(selectedProject.actual_income_amount) }} −
              выбытия {{ formatProjectCurrency(selectedProject.actual_expense_amount + selectedProject.actual_cost_amount) }}
            </div>
          </div>

          <div v-if="selectedForecast && !selectedForecast.isEmpty" class="rounded-lg border border-slate-200 p-3">
            <div class="text-xs text-slate-500">Прогноз затрат</div>
            <div class="text-lg font-semibold" :class="TONE_TEXT[selectedForecast.tone]">
              {{ selectedForecast.value }}
            </div>
            <div v-if="selectedForecast.deviation" class="text-xs" :class="TONE_TEXT[selectedForecast.tone]">
              {{ selectedForecast.deviation }}
            </div>
            <p class="mt-1 text-xs text-slate-500">{{ selectedForecast.explanation }}</p>
          </div>
          <p v-else-if="selectedForecast" class="text-xs text-slate-500">{{ selectedForecast.explanation }}</p>

          <p v-if="!selectedProject.has_budget" class="ms-note ms-note-info text-sm">
            {{ describeBddsNoBudget(selectedProject) }}
          </p>

          <p v-if="selectedRateGap" class="ms-note text-sm">{{ selectedRateGap }}</p>

          <p class="text-xs text-slate-400">
            Последнее списание: {{ formatBoardActivity(selectedProject) }}
          </p>

          <B24Button
            label="Открыть бюджет проекта"
            color="default"
            @click="openProject(selectedProject.project_id)"
          />
        </aside>
      </div>
    </template>
  </BddsGate>
</template>
