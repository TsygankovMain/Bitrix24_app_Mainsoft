<script setup lang="ts">
/**
 * Строка фильтра отчёта — «вариант A: родной портал».
 *
 * Фильтр стоит В ОДНУ СТРОКУ, как в CRM Битрикса: период, сотрудники,
 * проекты, сохранённые пресеты. До редизайна каждый из семи отчётов рисовал
 * фильтр сам, блоком с подписями сверху, и шапка отчёта занимала треть экрана.
 *
 * На узкой ширине строка переносится (`flex-wrap`), а не превращается в
 * горизонтальный скролл: скрытый за краем фильтр человек просто не найдёт.
 *
 * Компонент только РИСУЕТ. Разбор и слияние пресетов, сравнение наборов и все
 * подписи живут в app/utils/reportFilterPresets.ts и покрыты тестами (node:test
 * через tsx не резолвит .vue — что осталось бы здесь, ревью не проверило бы).
 */
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import Filter1Icon from '@bitrix24/b24icons-vue/main/Filter1Icon'
import Bookmark1Icon from '@bitrix24/b24icons-vue/main/Bookmark1Icon'
import TrashBinIcon from '@bitrix24/b24icons-vue/main/TrashBinIcon'
import UiDatePickerInput from '~/components/ui/DatePickerInput.vue'
import MultiSelectFilter from '~/components/common/MultiSelectFilter.vue'
import { getMonthRange, getWeekRange } from '~/utils/reportDateRange'
import { useReportFilterPresets } from '~/composables/useReportFilterPresets'
import {
  describeFilterSnapshot,
  hasActiveSelection,
  normalizeFilterSnapshot,
  REPORT_PRESET_NAME_MAX,
  type ReportFilterSnapshot,
} from '~/utils/reportFilterPresets'
import type { FilterMode, FilterOption } from '~/types/report'

const props = defineProps<{
  dateFrom: string
  dateTo: string
  employees: Array<string | number>
  employeeMode: FilterMode
  projects: Array<string | number>
  projectMode: FilterMode
  employeeOptions: FilterOption[]
  projectOptions: FilterOption[]
}>()

const emit = defineEmits<{
  'update:dateFrom': [value: string]
  'update:dateTo': [value: string]
  'update:employees': [value: Array<string | number>]
  'update:employeeMode': [value: FilterMode]
  'update:projects': [value: Array<string | number>]
  'update:projectMode': [value: FilterMode]
  /** Пресет применён целиком — отчёту это повод перестроиться разом, а не шесть раз. */
  applied: [snapshot: ReportFilterSnapshot]
}>()

const PERIOD_PRESETS = [
  { id: 'cur_week', label: 'Эта неделя' },
  { id: 'prev_week', label: 'Прошлая неделя' },
  { id: 'cur_month', label: 'Этот месяц' },
  { id: 'prev_month', label: 'Прошлый месяц' },
] as const

type PeriodPresetId = typeof PERIOD_PRESETS[number]['id']

const { presets, load: loadPresets, save: savePresetToStore, remove: removePresetFromStore, get: getPreset, matching: matchingPreset } = useReportFilterPresets()

const presetNameFieldId = useId()

const rootRef = ref<HTMLElement | null>(null)
const openMenu = ref<'' | 'period' | 'presets'>('')
const newPresetName = ref('')

const snapshot = computed<ReportFilterSnapshot>(() => normalizeFilterSnapshot({
  dateFrom: props.dateFrom,
  dateTo: props.dateTo,
  employees: props.employees,
  employeeMode: props.employeeMode,
  projects: props.projects,
  projectMode: props.projectMode,
}))

const activePreset = computed(() => matchingPreset(snapshot.value))
const canReset = computed(() => hasActiveSelection(snapshot.value))

const presetsButtonLabel = computed(() => (
  activePreset.value ? activePreset.value.name : 'Пресеты'
))

function describe(value: ReportFilterSnapshot): string {
  return describeFilterSnapshot(value)
}

function toggleMenu(name: 'period' | 'presets') {
  openMenu.value = openMenu.value === name ? '' : name
}

function closeMenus() {
  openMenu.value = ''
}

function applyPeriodPreset(id: PeriodPresetId) {
  const range = id === 'cur_week'
    ? getWeekRange(0)
    : id === 'prev_week'
      ? getWeekRange(-1)
      : id === 'cur_month'
        ? getMonthRange(0)
        : getMonthRange(-1)

  emit('update:dateFrom', range.dateFrom)
  emit('update:dateTo', range.dateTo)
  closeMenus()
}

function applySnapshot(next: ReportFilterSnapshot) {
  emit('update:dateFrom', next.dateFrom)
  emit('update:dateTo', next.dateTo)
  emit('update:employees', [...next.employees])
  emit('update:employeeMode', next.employeeMode)
  emit('update:projects', [...next.projects])
  emit('update:projectMode', next.projectMode)
  emit('applied', next)
}

function applyPreset(id: string) {
  const preset = getPreset(id)

  if (!preset) {
    return
  }

  applySnapshot(preset.filters)
  closeMenus()
}

function savePreset() {
  if (!savePresetToStore(newPresetName.value, snapshot.value)) {
    return
  }

  newPresetName.value = ''
}

function removePreset(id: string) {
  removePresetFromStore(id)
}

function resetSelection() {
  emit('update:employees', [])
  emit('update:employeeMode', 'include')
  emit('update:projects', [])
  emit('update:projectMode', 'include')
}

function handlePointerDown(event: MouseEvent | TouchEvent) {
  if (!openMenu.value) {
    return
  }

  const target = event.target as Node | null

  if (rootRef.value && target && !rootRef.value.contains(target)) {
    closeMenus()
  }
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeMenus()
  }
}

onMounted(() => {
  loadPresets()
  document.addEventListener('mousedown', handlePointerDown)
  document.addEventListener('touchstart', handlePointerDown, { passive: true })
  document.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handlePointerDown)
  document.removeEventListener('touchstart', handlePointerDown)
  document.removeEventListener('keydown', handleEscape)
})
</script>

<template>
  <div
    ref="rootRef"
    class="report-filter-bar flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-2.5"
    role="search"
    aria-label="Фильтр отчёта"
  >
    <Filter1Icon class="size-4 shrink-0 text-slate-400" aria-hidden="true" />

    <!-- Период -->
    <div class="flex flex-wrap items-center gap-1.5">
      <UiDatePickerInput
        :model-value="dateFrom"
        placeholder="Начало периода"
        @update:model-value="emit('update:dateFrom', $event)"
      />
      <span class="text-slate-400">—</span>
      <UiDatePickerInput
        :model-value="dateTo"
        placeholder="Конец периода"
        @update:model-value="emit('update:dateTo', $event)"
      />

      <div class="relative">
        <button
          type="button"
          class="inline-flex h-[38px] items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
          :aria-expanded="openMenu === 'period'"
          @click="toggleMenu('period')"
        >
          Период
          <span aria-hidden="true" class="text-slate-400">▾</span>
        </button>

        <div
          v-if="openMenu === 'period'"
          class="absolute left-0 z-30 mt-2 w-[200px] overflow-hidden rounded-2xl border border-slate-200 bg-white p-1 shadow-xl"
        >
          <button
            v-for="preset in PERIOD_PRESETS"
            :key="preset.id"
            type="button"
            class="block w-full rounded-lg px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50"
            @click="applyPeriodPreset(preset.id)"
          >
            {{ preset.label }}
          </button>
        </div>
      </div>
    </div>

    <!-- Сотрудники и проекты -->
    <MultiSelectFilter
      compact
      label="Сотрудники"
      :model-value="employees"
      :mode="employeeMode"
      :options="employeeOptions"
      @update:model-value="emit('update:employees', $event)"
      @update:mode="emit('update:employeeMode', $event)"
    />

    <MultiSelectFilter
      compact
      label="Проекты"
      :model-value="projects"
      :mode="projectMode"
      :options="projectOptions"
      @update:model-value="emit('update:projects', $event)"
      @update:mode="emit('update:projectMode', $event)"
    />

    <button
      v-if="canReset"
      type="button"
      class="h-[38px] rounded-lg px-2 text-sm font-medium text-slate-500 transition hover:text-slate-900"
      @click="resetSelection"
    >
      Сбросить
    </button>

    <div class="grow" />

    <!-- Сохранённые пресеты -->
    <div class="relative">
      <button
        type="button"
        class="inline-flex h-[38px] max-w-[220px] items-center gap-1.5 rounded-lg border px-3 text-sm font-medium shadow-sm transition"
        :class="activePreset
          ? 'border-[#0075ff] bg-blue-50 text-[#0075ff]'
          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'"
        :aria-expanded="openMenu === 'presets'"
        @click="toggleMenu('presets')"
      >
        <Bookmark1Icon class="size-4 shrink-0" aria-hidden="true" />
        <span class="truncate">{{ presetsButtonLabel }}</span>
        <span aria-hidden="true" class="text-slate-400">▾</span>
      </button>

      <div
        v-if="openMenu === 'presets'"
        class="absolute right-0 z-30 mt-2 w-[320px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
      >
        <div class="max-h-[280px] overflow-y-auto p-1">
          <p v-if="!presets.length" class="px-3 py-4 text-sm text-slate-400">
            Сохранённых фильтров пока нет. Выставьте период и отборы и сохраните их под именем.
          </p>

          <div
            v-for="preset in presets"
            :key="preset.id"
            class="flex items-start gap-1 rounded-lg transition hover:bg-slate-50"
            :class="activePreset?.id === preset.id ? 'bg-blue-50/60' : ''"
          >
            <button
              type="button"
              class="min-w-0 grow px-3 py-2 text-left"
              @click="applyPreset(preset.id)"
            >
              <span class="block truncate text-sm font-medium text-slate-800">{{ preset.name }}</span>
              <span class="block truncate text-xs text-slate-500">{{ describe(preset.filters) }}</span>
            </button>
            <button
              type="button"
              class="mt-2 mr-2 shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
              :title="`Удалить пресет «${preset.name}»`"
              :aria-label="`Удалить пресет «${preset.name}»`"
              @click="removePreset(preset.id)"
            >
              <TrashBinIcon class="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div class="border-t border-slate-100 p-3">
          <label class="block text-xs font-medium text-slate-500" :for="presetNameFieldId">
            Сохранить текущий фильтр
          </label>
          <p class="mt-1 truncate text-xs text-slate-400" :title="describe(snapshot)">
            {{ describe(snapshot) }}
          </p>
          <div class="mt-2 flex gap-2">
            <input
              :id="presetNameFieldId"
              v-model="newPresetName"
              type="text"
              :maxlength="REPORT_PRESET_NAME_MAX"
              placeholder="Например, «Мой отдел, месяц»"
              class="h-[34px] min-w-0 grow rounded-lg border border-slate-200 px-2.5 text-sm outline-none transition focus:border-[#0075ff]"
              @keydown.enter.prevent="savePreset"
            >
            <button
              type="button"
              class="h-[34px] shrink-0 rounded-lg bg-[#0075ff] px-3 text-sm font-medium text-white transition hover:bg-[#0062d6] disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!newPresetName.trim()"
              @click="savePreset"
            >
              Сохранить
            </button>
          </div>
          <p class="mt-2 text-[11px] leading-4 text-slate-400">
            Пресеты хранятся в этом браузере для вашего портала и учётной записи.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/*
 * Поля даты в строке фильтра уже, чем в форме.
 *
 * У DatePickerInput по умолчанию min-width 180px — это правильно для колонки с
 * подписями, но в строке из пяти полей два таких поля съедают почти половину
 * ширины фрейма 1000px и выталкивают пресеты на второй ряд. Сужаем только
 * здесь, чтобы не трогать сам пикер: он стоит ещё и в форме подстановки ИНН.
 */
.report-filter-bar :deep(.dp-wrapper) {
  min-width: 152px;
}
</style>
