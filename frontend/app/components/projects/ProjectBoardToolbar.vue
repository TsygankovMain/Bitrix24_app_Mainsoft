<script setup lang="ts">
/**
 * Строка фильтров над доской проектов.
 *
 * Зачем отдельный компонент: раньше фильтры жили прямо в шапке страницы
 * пятью полями в сетке `xl:grid-cols-[1.2fr_repeat(4,minmax(0,1fr))]` — на
 * ширине фрейма 1000 px это была вторая по высоте часть экрана после самой
 * доски. Здесь то же самое собрано в две строки: поля отбора и чипы быстрых
 * отборов со счётчиками.
 *
 * Логики тут нет — состояние фильтра целиком приходит и уходит наружу
 * (v-model), а считают его чистые функции из utils/projectBoardView.ts.
 */

import { computed } from 'vue'
import SearchableSelect from '~/components/common/SearchableSelect.vue'
import type { ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import type { ProjectBoardFilterState, ProjectBoardSortId } from '~/utils/projectBoardView'
import { PROJECT_BOARD_SORTS, countActiveBoardFilters } from '~/utils/projectBoardView'

type SearchableSelectSearchOutcome = {
  options: ProjectBoardDirectoryOption[]
  truncated?: boolean
  failed?: boolean
}

const props = defineProps<{
  curatorOptions: ProjectBoardDirectoryOption[]
  companyOptions: ProjectBoardDirectoryOption[]
  legalEntityOptions: ProjectBoardDirectoryOption[]
  companySearchFn?: (query: string) => Promise<SearchableSelectSearchOutcome>
  /** Сколько карточек показано и сколько всего — «показано 12 из 47». */
  shownCount: number
  totalCount: number
  mineCount: number
  riskCount: number
  /** Доска ещё не знает текущего пользователя: чип «Мои» отключаем, чтобы он не давал пустоту. */
  isUserKnown?: boolean
}>()

const emit = defineEmits<{
  (event: 'reset'): void
}>()

const filters = defineModel<ProjectBoardFilterState>({ required: true })

function patch(next: Partial<ProjectBoardFilterState>) {
  filters.value = { ...filters.value, ...next }
}

const searchQuery = computed({
  get: () => filters.value.search,
  set: (value: string) => patch({ search: value }),
})

const curatorId = computed({
  get: () => filters.value.curatorId,
  set: (value: string | number | null) => patch({ curatorId: String(value ?? '') }),
})

const companyId = computed({
  get: () => filters.value.companyId,
  set: (value: string | number | null) => patch({ companyId: String(value ?? '') }),
})

const legalEntityId = computed({
  get: () => filters.value.legalEntityId,
  set: (value: string | number | null) => patch({ legalEntityId: String(value ?? '') }),
})

const projectType = computed({
  get: () => filters.value.projectType,
  set: (value: ProjectBoardFilterState['projectType']) => patch({ projectType: value }),
})

const sort = computed({
  get: () => filters.value.sort,
  set: (value: ProjectBoardSortId) => patch({ sort: value }),
})

const activeFiltersCount = computed(() => countActiveBoardFilters(filters.value))

const isFiltered = computed(() => props.shownCount !== props.totalCount)

const chipClass = 'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition'
const chipIdleClass = 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'
const chipActiveClass = 'border-[#0075ff] bg-[#e8f3ff] text-[#0075ff]'
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-end gap-2">
      <label class="grid w-[220px] shrink-0 gap-1 text-xs">
        <span class="font-medium text-slate-700">Поиск</span>
        <input
          v-model="searchQuery"
          type="search"
          placeholder="Проект, компания, ИНН, куратор"
        >
      </label>

      <div class="w-[170px] shrink-0">
        <SearchableSelect
          v-model="curatorId"
          label="Куратор"
          empty-label="Все"
          search-placeholder="Поиск куратора"
          :options="curatorOptions"
        />
      </div>

      <div class="w-[190px] shrink-0">
        <SearchableSelect
          v-model="companyId"
          label="Клиент"
          empty-label="Все"
          search-placeholder="Название или ИНН"
          :options="companyOptions"
          :search-fn="companySearchFn"
        />
      </div>

      <div class="w-[170px] shrink-0">
        <SearchableSelect
          v-model="legalEntityId"
          label="Наше юрлицо"
          empty-label="Все"
          search-placeholder="Название или ИНН"
          :options="legalEntityOptions"
        />
      </div>

      <label class="grid w-[160px] shrink-0 gap-1 text-xs">
        <span class="font-medium text-slate-700">Тип</span>
        <select v-model="projectType">
          <option value="all">Все</option>
          <option value="support">Поддержка</option>
          <option value="delivery">Проектная работа</option>
        </select>
      </label>

      <label class="ml-auto grid w-[190px] shrink-0 gap-1 text-xs">
        <span class="font-medium text-slate-700">Порядок карточек</span>
        <select v-model="sort">
          <option v-for="item in PROJECT_BOARD_SORTS" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        type="button"
        :class="[chipClass, filters.onlyMine ? chipActiveClass : chipIdleClass, isUserKnown ? '' : 'cursor-not-allowed opacity-50']"
        :disabled="!isUserKnown"
        :title="isUserKnown ? 'Проекты, где я куратор' : 'Пользователь портала ещё не определился'"
        :aria-pressed="filters.onlyMine"
        @click="patch({ onlyMine: !filters.onlyMine })"
      >
        Мои
        <span class="text-[11px] opacity-70">{{ mineCount }}</span>
      </button>

      <button
        type="button"
        :class="[chipClass, filters.onlyRisk ? chipActiveClass : chipIdleClass]"
        title="Нет списаний 30+ дней или перерасход бюджета"
        :aria-pressed="filters.onlyRisk"
        @click="patch({ onlyRisk: !filters.onlyRisk })"
      >
        Под риском
        <span class="text-[11px] opacity-70">{{ riskCount }}</span>
      </button>

      <span class="text-xs text-slate-500">
        <template v-if="isFiltered">Показано {{ shownCount }} из {{ totalCount }}</template>
        <template v-else>Проектов: {{ totalCount }}</template>
      </span>

      <button
        v-if="activeFiltersCount > 0"
        type="button"
        class="ml-auto rounded-lg px-2.5 py-1 text-xs font-medium text-[#0075ff] transition hover:bg-[#e8f3ff]"
        @click="emit('reset')"
      >
        Сбросить фильтры ({{ activeFiltersCount }})
      </button>
    </div>
  </div>
</template>
