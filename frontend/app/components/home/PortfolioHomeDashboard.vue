<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ProjectBoardCardRecord } from '~/utils/projectBoard'
import type { ReportRoutePayload } from '~/utils/reportNavigation'
import {
  formatProjectDate,
  formatProjectHours,
  formatProjectMoney,
  getStageBadgeClass,
  parseProjectDateValue,
} from '~/utils/projectBoard'

type CuratorOption = {
  id: string
  name: string
}

type LeakageRow = {
  project_id?: string | null
  project_name: string
  total_hours: number
  billable_hours: number
  non_billable_hours: number
  loss_rate: number
}

type SnapshotData = {
  summary: {
    total_count: number
    active_count: number
    archived_count: number
    support_count: number
    inactive_30_count: number
    inactive_90_count: number
  }
  cards: ProjectBoardCardRecord[]
  stages: Array<{ id: string, title: string, kind?: string, can_drop?: boolean }>
  curators: CuratorOption[]
  risk_cards: ProjectBoardCardRecord[]
  top_loss_projects: LeakageRow[]
  warning?: string | null
  generated_at?: string | null
}

const props = defineProps<{
  data: SnapshotData | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (event: 'open-card', card: ProjectBoardCardRecord): void
  (event: 'open-board'): void
  (event: 'open-project', card: ProjectBoardCardRecord): void
  (event: 'open-report', payload: string | ReportRoutePayload): void
}>()

const previewMode = ref<'board' | 'timeline'>('board')
const curatorFilter = ref('all')
const searchQuery = ref('')
const signalsOnly = ref(false)
const selectedProjectId = ref('')

const previewStages = computed(() => {
  const stages = props.data?.stages || []
  if (stages.length > 0) {
    return stages
  }

  return [
    { id: 'В просчете', title: 'В просчете' },
    { id: 'В работе', title: 'В работе' },
    { id: 'Нет списаний 1 месяц', title: 'Нет списаний 1 месяц' },
    { id: 'Нет списаний 3 месяца', title: 'Нет списаний 3 месяца' },
  ]
})

const filteredCards = computed(() => {
  const cards = props.data?.cards || []
  const query = searchQuery.value.trim().toLowerCase()

  return cards.filter((card) => {
    if (signalsOnly.value && (card.last_writeoff_days || 0) < 30) {
      return false
    }

    if (curatorFilter.value !== 'all' && String(card.curator_user_id || '') !== curatorFilter.value) {
      return false
    }

    if (!query) {
      return true
    }

    return [
      card.project_name,
      card.company_name,
      card.curator_name,
      card.our_legal_entity_name,
      card.stage,
    ].some(value => String(value || '').toLowerCase().includes(query))
  })
})

const boardColumns = computed(() =>
  previewStages.value.map(stage => ({
    id: stage.id,
    title: stage.title,
    cards: filteredCards.value.filter(card => card.stage === stage.title),
  }))
)

const sortedTimelineCards = computed(() =>
  filteredCards.value
    .slice()
    .sort((left, right) => {
      const leftDate = normalizeDate(left.project_start_date || left.last_writeoff_at || left.created_at)
      const rightDate = normalizeDate(right.project_start_date || right.last_writeoff_at || right.created_at)
      return leftDate.getTime() - rightDate.getTime()
    })
)

const selectedProject = computed(() => {
  const cards = filteredCards.value
  if (!cards.length) {
    return null
  }

  if (selectedProjectId.value) {
    const selected = cards.find(card => card.project_id === selectedProjectId.value)
    if (selected) {
      return selected
    }
  }

  return cards[0]
})

watch(
  () => filteredCards.value,
  (cards) => {
    if (!cards.length) {
      selectedProjectId.value = ''
      return
    }

    if (!selectedProjectId.value || !cards.some(card => card.project_id === selectedProjectId.value)) {
      selectedProjectId.value = cards[0].project_id
    }
  },
  { immediate: true }
)

function selectProject(card: ProjectBoardCardRecord) {
  selectedProjectId.value = card.project_id
}

function normalizeDate(value?: string | null) {
  const parsed = parseProjectDateValue(value)
  return Number.isNaN(parsed.getTime()) ? new Date(0) : parsed
}

function getTimelineStyle(card: ProjectBoardCardRecord, index: number) {
  const width = Math.max(18, Math.min((card.project_hours_budget || 240) / 12, 72))
  const left = 4 + (index % 6) * 12
  return {
    left: `${left}%`,
    width: `${width}%`,
  }
}
</script>

<template>
  <div class="space-y-6">
    <section class="ms-surface-hero overflow-hidden p-5">
      <div class="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_auto] xl:items-start">
        <div class="min-w-0">
          <div class="ms-eyebrow">
            Portfolio Home
          </div>
          <div
            v-if="data?.warning"
            class="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700"
          >
            {{ data.warning }}
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2 xl:justify-end">
          <div class="ms-segmented">
            <button
              type="button"
              :class="[
                'ms-segmented-btn',
                previewMode === 'board' ? 'ms-segmented-btn-active-dark' : '',
              ]"
              @click="previewMode = 'board'"
            >
              Board preview
            </button>
            <button
              type="button"
              :class="[
                'ms-segmented-btn',
                previewMode === 'timeline' ? 'ms-segmented-btn-active-dark' : '',
              ]"
              @click="previewMode = 'timeline'"
            >
              Timeline preview
            </button>
          </div>

          <B24Button label="Открыть Project Board" color="success" @click="emit('open-board')" />
        </div>
      </div>

      <div class="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article class="ms-stat-card">
          <div class="text-xs text-slate-400">Проектов в работе</div>
          <div class="mt-2 text-3xl font-semibold text-slate-900">{{ data?.summary.active_count || 0 }}</div>
          <div class="mt-1 text-xs text-slate-500">Активный портфель</div>
        </article>
        <article class="ms-stat-card">
          <div class="text-xs text-slate-400">Нет списаний 1 месяц</div>
          <div class="mt-2 text-3xl font-semibold text-amber-600">{{ data?.summary.inactive_30_count || 0 }}</div>
          <div class="mt-1 text-xs text-slate-500">Требуют внимания</div>
        </article>
        <article class="ms-stat-card">
          <div class="text-xs text-slate-400">Нет списаний 3 месяца</div>
          <div class="mt-2 text-3xl font-semibold text-rose-600">{{ data?.summary.inactive_90_count || 0 }}</div>
          <div class="mt-1 text-xs text-slate-500">Высокий риск потери</div>
        </article>
        <article class="ms-stat-card">
          <div class="text-xs text-slate-400">Support-проекты</div>
          <div class="mt-2 text-3xl font-semibold text-cyan-700">{{ data?.summary.support_count || 0 }}</div>
          <div class="mt-1 text-xs text-slate-500">Отдельный режим работы</div>
        </article>
      </div>
    </section>

    <section class="ms-filter-wrap grid gap-3 xl:grid-cols-[1.1fr_1fr_auto_auto]">
      <label class="grid gap-1 text-sm">
        <span class="font-medium text-slate-700">Куратор</span>
        <select
          v-model="curatorFilter"
          class="rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
        >
          <option value="all">Все</option>
          <option v-for="curator in data?.curators || []" :key="curator.id" :value="curator.id">
            {{ curator.name }}
          </option>
        </select>
      </label>

      <label class="grid gap-1 text-sm">
        <span class="font-medium text-slate-700">Поиск проекта</span>
        <input
          v-model="searchQuery"
          type="search"
          placeholder="Например, ACME"
          class="rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
        >
      </label>

      <button type="button" class="ms-action-card text-center" @click="signalsOnly = !signalsOnly">
        {{ signalsOnly ? 'Все проекты' : 'Показать сигналы' }}
      </button>

      <B24Button label="Открыть Project Board" color="default" @click="emit('open-board')" />
    </section>

    <div class="grid gap-6 xl:grid-cols-[1.7fr_0.9fr]">
      <section class="ms-surface p-5">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Портфель</h3>
            <p class="mt-1 text-sm text-slate-500">Просмотр доски или таймлайна без перехода в отдельный модуль.</p>
          </div>
          <div class="text-xs text-slate-400">
            {{ filteredCards.length }} проектов после фильтров
          </div>
        </div>

        <div v-if="loading" class="py-12 text-center text-sm text-slate-500">
          Загружаем портфель...
        </div>

        <div v-else-if="!filteredCards.length" class="py-12 text-center text-sm text-slate-500">
          По текущим фильтрам проектов не найдено.
        </div>

        <div
          v-else-if="previewMode === 'board'"
          class="mt-5 grid gap-4"
          :style="{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }"
        >
          <section
            v-for="column in boardColumns"
            :key="column.id"
            class="rounded-2xl border border-slate-200 bg-slate-50 p-3"
          >
            <div class="flex items-center justify-between gap-3">
              <h4 class="text-sm font-semibold text-slate-900">{{ column.title }}</h4>
              <span class="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">{{ column.cards.length }}</span>
            </div>

            <div class="mt-3 space-y-2">
              <button
                v-for="card in column.cards.slice(0, 4)"
                :key="card.project_id"
                type="button"
                class="w-full rounded-2xl border border-white bg-white px-3 py-3 text-left shadow-sm transition hover:border-lime-200 hover:shadow"
                @click="selectProject(card)"
              >
                <div class="truncate text-sm font-semibold text-slate-900">{{ card.project_name }}</div>
                <div class="mt-1 text-xs text-slate-500">{{ card.company_name || 'Без компании' }}</div>
                <div class="mt-2 text-[11px] text-slate-400">{{ card.our_legal_entity_name || 'Юрлицо не выбрано' }}</div>
              </button>

              <div v-if="column.cards.length === 0" class="rounded-2xl border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
                Нет проектов
              </div>
            </div>
          </section>
        </div>

        <div v-else class="mt-5 space-y-3">
          <button
            v-for="(card, index) in sortedTimelineCards.slice(0, 8)"
            :key="card.project_id"
            type="button"
            class="grid w-full grid-cols-[220px_minmax(0,1fr)] gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-left transition hover:border-lime-200"
            @click="selectProject(card)"
          >
            <div class="min-w-0">
              <div class="truncate text-sm font-semibold text-slate-900">{{ card.project_name }}</div>
              <div class="mt-1 text-xs text-slate-500">{{ card.company_name || 'Без компании' }}</div>
            </div>

            <div class="relative h-10 overflow-hidden rounded-2xl bg-white px-3">
              <div class="absolute inset-x-3 top-1/2 h-2 -translate-y-1/2 rounded-full bg-slate-200" />
              <div
                :class="['absolute top-1/2 h-5 -translate-y-1/2 rounded-full shadow-sm', getStageBadgeClass(card.stage)]"
                :style="getTimelineStyle(card, index)"
              />
            </div>
          </button>
        </div>
      </section>

      <aside class="ms-surface p-5">
        <template v-if="selectedProject">
          <div class="flex flex-wrap gap-2">
            <span :class="['inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', getStageBadgeClass(selectedProject.stage)]">
              {{ selectedProject.stage }}
            </span>
            <span
              v-if="(selectedProject.last_writeoff_days || 0) >= 30"
              class="inline-flex rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-700"
            >
              {{ selectedProject.last_writeoff_days }} дн. без списаний
            </span>
          </div>

          <h3 class="mt-4 text-xl font-semibold text-slate-900">{{ selectedProject.project_name }}</h3>
          <p class="mt-1 text-sm text-slate-500">
            {{ selectedProject.company_name || 'Без компании' }} · куратор {{ selectedProject.curator_name || 'не назначен' }}
          </p>

          <div class="mt-5 grid gap-3 sm:grid-cols-2">
            <div class="rounded-2xl bg-slate-50 px-4 py-3">
              <div class="text-xs text-slate-400">Наше юрлицо</div>
              <div class="mt-1 text-sm font-semibold text-slate-900">{{ selectedProject.our_legal_entity_name || 'Не выбрано' }}</div>
            </div>
            <div class="rounded-2xl bg-slate-50 px-4 py-3">
              <div class="text-xs text-slate-400">Объем / support</div>
              <div class="mt-1 text-sm font-semibold text-slate-900">
                {{ selectedProject.is_support ? 'Support' : formatProjectHours(selectedProject.project_hours_budget) }}
              </div>
            </div>
            <div class="rounded-2xl bg-slate-50 px-4 py-3">
              <div class="text-xs text-slate-400">Ставка</div>
              <div class="mt-1 text-sm font-semibold text-slate-900">{{ formatProjectMoney(selectedProject.hourly_rate) }}</div>
            </div>
            <div class="rounded-2xl bg-slate-50 px-4 py-3">
              <div class="text-xs text-slate-400">Последнее списание</div>
              <div class="mt-1 text-sm font-semibold text-slate-900">
                {{ selectedProject.last_writeoff_at ? formatProjectDate(selectedProject.last_writeoff_at) : 'Нет данных' }}
              </div>
            </div>
          </div>

          <div class="mt-5 flex flex-wrap gap-2">
            <B24Button label="Открыть карточку проекта" color="success" @click="emit('open-card', selectedProject)" />
            <B24Button
              label="Открыть проект"
              color="default"
              @click="emit('open-project', selectedProject)"
            />
          </div>
        </template>

        <div v-else class="py-10 text-center text-sm text-slate-500">
          Выберите проект слева, чтобы увидеть executive snapshot.
        </div>
      </aside>
    </div>

    <div class="grid gap-6 xl:grid-cols-3">
      <section class="ms-surface p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Проекты без списаний</h3>
            <p class="mt-1 text-sm text-slate-500">Самый частый управленческий сигнал прямо на старте.</p>
          </div>
        </div>

        <div class="mt-4 space-y-3">
          <button
            v-for="card in data?.risk_cards || []"
            :key="card.project_id"
            type="button"
            class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-amber-200"
            @click="selectProject(card)"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-slate-900">{{ card.project_name }}</div>
                <div class="mt-1 text-xs text-slate-500">{{ card.company_name || 'Без компании' }}</div>
              </div>
              <span class="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">
                {{ card.last_writeoff_days || 0 }} дн.
              </span>
            </div>
          </button>

          <div v-if="!(data?.risk_cards || []).length" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
            Сейчас нет проектов с критичной паузой по списаниям.
          </div>
        </div>
      </section>

      <section class="ms-surface p-5">
        <h3 class="text-lg font-semibold text-slate-900">Где теряем деньги</h3>
        <p class="mt-1 text-sm text-slate-500">Топ проектов по неучтенным часам за последние 90 дней.</p>

        <div class="mt-4 space-y-3">
          <article
            v-for="row in data?.top_loss_projects || []"
            :key="`${row.project_id || row.project_name}`"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-semibold text-slate-900">{{ row.project_name }}</div>
                <div class="mt-1 text-xs text-slate-500">{{ row.total_hours }} ч всего</div>
              </div>
              <span class="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700">
                {{ row.loss_rate }}%
              </span>
            </div>
            <div class="mt-3 text-xs text-slate-500">Неучтенные часы: {{ row.non_billable_hours }} ч</div>
          </article>

          <div v-if="!(data?.top_loss_projects || []).length" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
            Пока нет данных по потерям выручки.
          </div>
        </div>
      </section>

      <section class="ms-surface p-5">
        <h3 class="text-lg font-semibold text-slate-900">Маршруты в отчеты</h3>
        <p class="mt-1 text-sm text-slate-500">Навигация вокруг проектного контура, а не списка плиток.</p>

        <div class="mt-4 grid gap-3">
          <button
            type="button"
            class="ms-action-card"
            @click="emit('open-report', 'project')"
          >
            Отчет по проектам
          </button>
          <button
            type="button"
            class="ms-action-card"
            @click="emit('open-report', 'project-task')"
          >
            Учет по проектам/задачам
          </button>
          <button
            type="button"
            class="ms-action-card"
            @click="emit('open-report', 'revenue-leakage')"
          >
            Потери выручки
          </button>
          <button
            type="button"
            class="ms-action-card"
            @click="emit('open-report', 'daily')"
          >
            Ежедневная нагрузка
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
