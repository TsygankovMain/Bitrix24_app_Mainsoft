<script setup lang="ts">
/**
 * Единая шапка отчёта — «вариант A: родной портал».
 *
 * До редизайна каждый из семи отчётов рисовал обвязку сам: три разных каркаса
 * (`B24PageHeader`, `ms-page-shell` + `ProseH2`, самописная вёрстка), фильтр
 * блоком с подписями сверху, свежесть данных в одном месте, итоги — в другом,
 * кнопка «Назад» у каждого. Здесь всё это собрано один раз:
 *
 *  - название и пояснение;
 *  - свежесть данных («данные на ЧЧ:ММ» + «Обновить») — механика уже была в
 *    DataFreshnessIndicator, она переиспользуется как есть;
 *  - кнопки «Excel» и «Сформировать»;
 *  - строка фильтра в одну строку с сохранёнными пресетами (ReportFilterBar);
 *  - итоги (слот `totals`, обычно ReportTotalsStrip).
 *
 * Кнопки «Назад» здесь НЕТ намеренно: навигация теперь постоянная (меню
 * разделов в layouts/default.vue), и «Назад» на главную из отчёта — ровно тот
 * лишний возврат, который меню убрало.
 *
 * Состояния «загрузка / нет данных / ещё не формировали» тоже здесь: они были
 * одинаковыми во всех семи отчётах и расходились только формулировками.
 *
 * ДАННЫЕ ОТЧЁТА КОМПОНЕНТ НЕ ТРОГАЕТ. Он ничего не запрашивает и ничего не
 * считает — только отдаёт наверх события «сформировать», «выгрузить»,
 * «данные обновились».
 */
import DataFreshnessIndicator from '~/components/common/DataFreshnessIndicator.vue'
import ReportFilterBar from '~/components/reports/ReportFilterBar.vue'
import type { ReportFilterSnapshot } from '~/utils/reportFilterPresets'
import type { FilterMode, FilterOption } from '~/types/report'

withDefaults(defineProps<{
  title: string
  description?: string
  dateFrom: string
  dateTo: string
  employees: Array<string | number>
  employeeMode: FilterMode
  projects: Array<string | number>
  projectMode: FilterMode
  employeeOptions: FilterOption[]
  projectOptions: FilterOption[]
  /** Отчёт сейчас считается. */
  isLoading?: boolean
  /** Кнопку «Сформировать» уже нажимали хотя бы раз. */
  hasGenerated?: boolean
  /** Отчёт сформирован, но строк в нём нет. */
  isEmpty?: boolean
  exportDisabled?: boolean
  exportLabel?: string
  /** Предупреждение синхронизации: показываем над содержимым, но отчёт рисуем. */
  warning?: string
  /**
   * Обернуть содержимое в общую белую панель.
   *
   * Отчёты с таблицей — да. Отчёты, которые сами выкладывают несколько панелей
   * (потери выручки, дисциплина, фокус), — нет: вторая рамка вокруг рамок
   * только съедает ширину.
   */
  surface?: boolean
}>(), {
  description: '',
  isLoading: false,
  hasGenerated: false,
  isEmpty: false,
  exportDisabled: false,
  exportLabel: 'Excel',
  warning: '',
  surface: true,
})

const emit = defineEmits<{
  'update:dateFrom': [value: string]
  'update:dateTo': [value: string]
  'update:employees': [value: Array<string | number>]
  'update:employeeMode': [value: FilterMode]
  'update:projects': [value: Array<string | number>]
  'update:projectMode': [value: FilterMode]
  generate: []
  export: []
  refreshed: []
  'filters-applied': [snapshot: ReportFilterSnapshot]
}>()
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame flex flex-col gap-4">
      <!-- Единая шапка: название, свежесть данных, действия, фильтр, итоги -->
      <section class="ms-surface flex flex-col gap-3 p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h1 class="text-xl font-semibold tracking-tight text-slate-900">{{ title }}</h1>
            <p v-if="description" class="mt-1 text-sm text-slate-500">{{ description }}</p>
          </div>

          <div class="flex flex-wrap items-center justify-end gap-3">
            <DataFreshnessIndicator @refreshed="emit('refreshed')" />
            <div class="flex flex-wrap gap-2">
              <slot name="actions" />
              <B24Button
                :label="exportLabel"
                color="success"
                :disabled="exportDisabled"
                loading-auto
                @click="emit('export')"
              />
              <B24Button label="Сформировать" loading-auto @click="emit('generate')" />
            </div>
          </div>
        </div>

        <ReportFilterBar
          :date-from="dateFrom"
          :date-to="dateTo"
          :employees="employees"
          :employee-mode="employeeMode"
          :projects="projects"
          :project-mode="projectMode"
          :employee-options="employeeOptions"
          :project-options="projectOptions"
          @update:date-from="emit('update:dateFrom', $event)"
          @update:date-to="emit('update:dateTo', $event)"
          @update:employees="emit('update:employees', $event)"
          @update:employee-mode="emit('update:employeeMode', $event)"
          @update:projects="emit('update:projects', $event)"
          @update:project-mode="emit('update:projectMode', $event)"
          @applied="emit('filters-applied', $event)"
        />

        <slot name="totals" />
      </section>

      <div v-if="warning" class="ms-panel-warning">{{ warning }}</div>

      <div v-if="isLoading" class="ms-surface ms-empty-state">Загрузка…</div>
      <div v-else-if="!hasGenerated" class="ms-surface ms-empty-state">
        Выберите фильтры и нажмите «Сформировать»
      </div>
      <div v-else-if="isEmpty" class="ms-surface ms-empty-state">
        Нет данных за выбранный период
      </div>

      <div v-else :class="surface ? 'ms-surface ms-report-surface p-4' : 'flex flex-col gap-4'">
        <slot />
      </div>
    </div>
  </div>
</template>
