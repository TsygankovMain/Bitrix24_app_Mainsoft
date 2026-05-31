<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import ReportMetricCard from './ReportMetricCard.vue'
import MultiSelectFilter from '../common/MultiSelectFilter.vue'
import DateRangeFilter from '../common/DateRangeFilter.vue'
import { useReportFilters } from '~/composables/useReportFilters'
import { formatReportDate } from '~/utils/reportFormat'
import type { InnScanResult, InnBackfillRow, InnBackfillGroup, InnApplyItem } from '~/types/inn'
import InnAssignModal from './InnAssignModal.vue'
import { useProgress } from '~/composables/useProgress'

const apiStore = useApiStore()

const {
  dateFrom,
  dateTo,
  filterOptions,
  selectedProjects,
  loadFilterOptions,
  initCurrentMonthRange
} = useReportFilters()

// Простановка идёт чанками, чтобы не упереться в таймаут на больших объёмах
const CHUNK = 25
const globalProgress = useProgress()

const result = ref<InnScanResult | null>(null)
const loading = ref(false)
const applying = ref(false)
const message = ref<string>('')
const errorMessage = ref<string>('')

// выбор карточек и ручной ввод
const selected = ref<Set<string>>(new Set())
const manual = reactive<Record<string, { our?: string, client?: string }>>({})

const kpi = computed(() => result.value?.kpi ?? { total: 0, without_inn: 0, resolvable: 0, attention: 0 })
const hasResult = computed(() => !!result.value)

function key(row: InnBackfillRow): string {
  return String(row.bitrix_id)
}

function allRows(): InnBackfillRow[] {
  return (result.value?.groups ?? []).flatMap(g => g.rows)
}

function isSelected(row: InnBackfillRow): boolean {
  return selected.value.has(key(row))
}

function toggleRow(row: InnBackfillRow) {
  const k = key(row)
  if (selected.value.has(k)) selected.value.delete(k)
  else selected.value.add(k)
  selected.value = new Set(selected.value)
}

function groupAllSelected(rows: InnBackfillRow[]): boolean {
  return rows.length > 0 && rows.every(isSelected)
}

function toggleGroup(rows: InnBackfillRow[]) {
  const allOn = groupAllSelected(rows)
  for (const r of rows) {
    if (allOn) selected.value.delete(key(r))
    else selected.value.add(key(r))
  }
  selected.value = new Set(selected.value)
}

function manualFor(row: InnBackfillRow): { our?: string, client?: string } {
  const k = key(row)
  if (!manual[k]) manual[k] = {}
  return manual[k]
}

function rowToItem(row: InnBackfillRow): InnApplyItem {
  const m = manual[key(row)] ?? {}
  const our = row.our_blank ? ((m.our ?? '').trim() || row.suggest_our_inn) : ''
  const client = row.client_blank ? ((m.client ?? '').trim() || row.suggest_client_inn) : ''
  return { bitrix_id: row.bitrix_id, our_inn: our, client_inn: client }
}

const selectedCount = computed(() => selected.value.size)
const selectedReadyCount = computed(() =>
  allRows().filter(r => isSelected(r)).filter(r => {
    const it = rowToItem(r)
    return it.our_inn || it.client_inn
  }).length
)

async function runScan() {
  loading.value = true
  errorMessage.value = ''
  message.value = ''
  selected.value = new Set()
  try {
    result.value = await apiStore.scanInnBackfill(
      dateFrom.value,
      dateTo.value,
      selectedProjects.value.map(String)
    )
  } catch (e: any) {
    errorMessage.value = e?.data?.error || e?.message || 'Ошибка при поиске карточек'
    result.value = null
  } finally {
    loading.value = false
  }
}

async function applyItems(items: InnApplyItem[]) {
  const payload = items.filter(it => it.our_inn || it.client_inn)
  if (!payload.length) {
    errorMessage.value = 'Нет карточек с готовым ИНН для простановки'
    return
  }
  applying.value = true
  errorMessage.value = ''
  message.value = ''
  let updated = 0
  let failedCount = 0
  globalProgress.begin('Простановка ИНН…', payload.length)
  try {
    for (let i = 0; i < payload.length; i += CHUNK) {
      const chunk = payload.slice(i, i + CHUNK)
      const res = await apiStore.applyInnBackfill(chunk)
      updated += res.updated
      failedCount += res.failed.length
      globalProgress.update(Math.min(i + CHUNK, payload.length))
    }
    message.value = `Проставлено: ${updated}` + (failedCount ? `, ошибок: ${failedCount}` : '')
    await runScan()
  } catch (e: any) {
    errorMessage.value = e?.data?.error || e?.message || 'Ошибка при простановке ИНН'
  } finally {
    applying.value = false
    globalProgress.end()
  }
}

function applySelected() {
  applyItems(allRows().filter(isSelected).map(rowToItem))
}

function fillAllPossible() {
  applyItems(allRows().filter(r => r.status === 'ready').map(rowToItem))
}

function groupReadyCount(rows: InnBackfillRow[]): number {
  return rows.filter(r => r.status === 'ready').length
}

// Сворачивание групп
const collapsed = ref<Set<string>>(new Set())
function toggleCollapse(key: string) {
  collapsed.value.has(key) ? collapsed.value.delete(key) : collapsed.value.add(key)
  collapsed.value = new Set(collapsed.value)
}
function isCollapsed(key: string): boolean {
  return collapsed.value.has(key)
}

// Окно заполнения/замены ИНН на проект
const modal = ref<{ open: boolean, projectId: string, projectName: string, ourInn: string, clientInn: string }>({
  open: false, projectId: '', projectName: '', ourInn: '', clientInn: ''
})
function openAssign(group: InnBackfillGroup) {
  modal.value = {
    open: true,
    projectId: group.project_id || '',
    projectName: group.project_name,
    ourInn: group.our_inn,
    clientInn: group.client_inn
  }
}
function onAssigned() {
  modal.value.open = false
  runScan()
}

onMounted(async () => {
  initCurrentMonthRange()
  try {
    await loadFilterOptions()
  } catch {
    // опции проектов опциональны
  }
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- Шапка -->
    <div class="flex flex-row justify-between items-start w-full gap-4">
      <div>
        <ProseH2 class="!text-slate-900">Дозаполнение ИНН в списаниях</ProseH2>
        <p class="mt-1 text-xs text-slate-500">Поиск карточек без ИНН за период и простановка из проекта</p>
      </div>
      <div class="flex gap-2 shrink-0">
        <B24Button label="Найти" @click="runScan" :loading="loading" />
        <B24Button
          label="Заполнить всё возможное"
          color="success"
          :disabled="!hasResult || kpi.resolvable === 0 || applying"
          @click="fillAllPossible"
        />
      </div>
    </div>

    <!-- Фильтры -->
    <div class="ms-filter-wrap flex flex-wrap items-end gap-4">
      <DateRangeFilter v-model:dateFrom="dateFrom" v-model:dateTo="dateTo" />
      <MultiSelectFilter
        label="Проекты"
        :options="filterOptions.projects"
        v-model="selectedProjects"
      />
    </div>

    <!-- Сообщения -->
    <div v-if="message" class="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-2 text-sm text-emerald-700">{{ message }}</div>
    <div v-if="errorMessage" class="rounded-lg bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">{{ errorMessage }}</div>
    <div v-if="result?.warning" class="rounded-lg bg-amber-50 border border-amber-200 px-4 py-2 text-sm text-amber-700">{{ result.warning }}</div>

    <!-- Загрузка -->
    <div v-if="loading" class="ms-empty-state">Поиск карточек…</div>

    <!-- Результат -->
    <template v-else-if="hasResult">
      <!-- KPI -->
      <div class="ms-kpi-grid">
        <ReportMetricCard label="Всего за период" :value="kpi.total" tone="default" caption="карточек списания" />
        <ReportMetricCard label="Без ИНН" :value="kpi.without_inn" tone="warning" caption="хотя бы одно поле пусто" />
        <ReportMetricCard label="Можно проставить" :value="kpi.resolvable" tone="success" caption="ИНН есть в проекте" />
        <ReportMetricCard label="Требуют внимания" :value="kpi.attention" tone="danger" caption="нет ИНН / нет проекта" />
      </div>

      <!-- Пусто -->
      <div v-if="!result?.groups.length" class="ms-empty-state">
        За период не найдено карточек без ИНН — всё заполнено 🎉
      </div>

      <!-- Таблица групп -->
      <div v-else class="ms-table-shell">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50">
            <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <th class="px-3 py-3 w-8"></th>
              <th class="px-3 py-3">Дата</th>
              <th class="px-3 py-3">Сотрудник</th>
              <th class="px-3 py-3">Задача</th>
              <th class="px-3 py-3">Наш ИНН</th>
              <th class="px-3 py-3">ИНН клиента</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <template v-for="group in result?.groups" :key="group.key">
              <!-- Заголовок группы -->
              <tr class="bg-lime-50/60">
                <td class="px-3 py-2.5">
                  <input type="checkbox" :checked="groupAllSelected(group.rows)" @change="toggleGroup(group.rows)">
                </td>
                <td class="px-3 py-2.5 font-bold text-lime-800" colspan="3">
                  <span class="cursor-pointer select-none mr-1 text-lime-700" @click="toggleCollapse(group.key)">{{ isCollapsed(group.key) ? '▶' : '▼' }}</span>
                  {{ group.project_name }} · {{ group.count }} карт.
                  <span v-if="groupReadyCount(group.rows)" class="ml-2 inline-flex rounded bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">готовы {{ groupReadyCount(group.rows) }}</span>
                </td>
                <td class="px-3 py-2.5 text-xs">
                  <span v-if="group.our_inn" class="text-sky-800">наш: {{ group.our_inn }}</span>
                  <span v-else class="text-amber-700">наш ИНН не определён</span>
                </td>
                <td class="px-3 py-2.5 text-xs">
                  <span v-if="group.client_inn" class="text-sky-800">клиент: {{ group.client_inn }}</span>
                  <span v-else class="text-amber-700">клиент не определён</span>
                  <button
                    v-if="group.project_id"
                    class="ml-2 font-semibold text-sky-700 hover:underline"
                    :disabled="applying"
                    @click="openAssign(group)"
                  >Заполнить / Изменить ИНН →</button>
                </td>
              </tr>

              <!-- Строки карточек -->
              <template v-if="!isCollapsed(group.key)">
              <tr
                v-for="row in group.rows"
                :key="row.bitrix_id"
                class="hover:bg-slate-50"
                :class="row.status === 'no_project' ? 'bg-red-50/30' : (row.status === 'attention' ? 'bg-amber-50/30' : '')"
              >
                <td class="px-3 py-2"><input type="checkbox" :checked="isSelected(row)" @change="toggleRow(row)"></td>
                <td class="px-3 py-2 text-slate-500" style="padding-left:1.5rem">{{ formatReportDate(row.date) }}</td>
                <td class="px-3 py-2 text-slate-700">{{ row.employee_name }}</td>
                <td class="px-3 py-2 text-slate-600">{{ row.task }}</td>
                <!-- Наш ИНН -->
                <td class="px-3 py-2">
                  <span v-if="!row.our_blank" class="text-xs text-slate-400">заполнен</span>
                  <span v-else-if="row.suggest_our_inn" class="inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">✓ {{ row.suggest_our_inn }}</span>
                  <input v-else v-model="manualFor(row).our" class="w-32 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="наш ИНН">
                </td>
                <!-- ИНН клиента -->
                <td class="px-3 py-2">
                  <span v-if="!row.client_blank" class="text-xs text-slate-400">заполнен</span>
                  <span v-else-if="row.suggest_client_inn" class="inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">✓ {{ row.suggest_client_inn }}</span>
                  <input v-else v-model="manualFor(row).client" class="w-32 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="ИНН клиента">
                </td>
              </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Нижняя панель -->
      <div v-if="result?.groups.length" class="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3">
        <div class="text-sm text-slate-600">
          Выбрано: <b>{{ selectedCount }}</b> · с готовым ИНН: <b class="text-emerald-700">{{ selectedReadyCount }}</b>
        </div>
        <B24Button
          label="Проставить выбранным"
          color="success"
          :loading="applying"
          :disabled="selectedReadyCount === 0"
          @click="applySelected"
        />
      </div>
    </template>

    <!-- Начальное состояние -->
    <div v-else class="ms-empty-state">Выберите период и нажмите «Найти»</div>

    <InnAssignModal
      :visible="modal.open"
      :project-id="modal.projectId"
      :project-name="modal.projectName"
      :our-inn="modal.ourInn"
      :client-inn="modal.clientInn"
      :date-from="dateFrom"
      :date-to="dateTo"
      @close="modal.open = false"
      @applied="onAssigned"
    />
  </div>
</template>
