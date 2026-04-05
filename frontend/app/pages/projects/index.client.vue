<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import ProjectBoardColumn from '~/components/projects/ProjectBoardColumn.vue'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'
import ProjectTimelineLane from '~/components/projects/ProjectTimelineLane.vue'
import type { ProjectBoardCardRecord, ProjectBoardResponse } from '~/utils/projectBoard'
import { formatProjectDate, getTimelineAnchor, parseProjectDateValue } from '~/utils/projectBoard'

const router = useRouter()
const { locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Управление проектами',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('ProjectBoardPage')
const { $initializeB24Frame } = useNuxtApp()

let $b24: null | B24Frame = null

const apiStore = useApiStore()

const isInit = ref(false)
const isLoading = ref(false)
const isSyncing = ref(false)
const isSaving = ref(false)
const isArchiving = ref(false)

const boardData = ref<ProjectBoardResponse | null>(null)
const employees = ref<Array<{ id: string | number; name: string | number }>>([])
const companies = ref<Array<{ id: string | number; name: string | number }>>([])
const legalEntities = ref<Array<{ id: string | number; name: string | number }>>([])

const activeView = ref<'board' | 'timeline' | 'archive'>('board')
const searchQuery = ref('')
const supportFilter = ref<'all' | 'support' | 'delivery'>('all')
const curatorFilter = ref('')
const companyFilter = ref('')
const legalEntityFilter = ref('')

const selectedCard = ref<ProjectBoardCardRecord | null>(null)
const isDrawerOpen = ref(false)
const draggedProjectId = ref<string | null>(null)
const statusMessage = ref<{ type: 'success' | 'warning' | 'error'; text: string } | null>(null)

const messageClass = computed(() => {
  if (!statusMessage.value) {
    return ''
  }

  if (statusMessage.value.type === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }

  if (statusMessage.value.type === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700'
  }

  return 'border-red-200 bg-red-50 text-red-700'
})

const allCards = computed(() => boardData.value?.cards || [])

const filteredCards = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  return allCards.value.filter((card) => {
    if (supportFilter.value === 'support' && !card.is_support) {
      return false
    }

    if (supportFilter.value === 'delivery' && card.is_support) {
      return false
    }

    if (curatorFilter.value && String(card.curator_user_id || '') !== curatorFilter.value) {
      return false
    }

    if (companyFilter.value && String(card.company_id || '') !== companyFilter.value) {
      return false
    }

    if (legalEntityFilter.value && String(card.our_legal_entity_id || '') !== legalEntityFilter.value) {
      return false
    }

    if (!query) {
      return true
    }

    return [
      card.project_name,
      card.project_id,
      card.curator_name,
      card.company_name,
      card.our_legal_entity_name,
      card.stage
    ].some(value => String(value || '').toLowerCase().includes(query))
  })
})

const activeCards = computed(() =>
  filteredCards.value
    .filter(card => !card.is_archived)
    .slice()
    .sort((left, right) => left.project_name.localeCompare(right.project_name, 'ru'))
)

const archivedCards = computed(() =>
  filteredCards.value
    .filter(card => card.is_archived)
    .slice()
    .sort((left, right) => left.project_name.localeCompare(right.project_name, 'ru'))
)

const stageColumns = computed(() =>
  (boardData.value?.stages || []).map(stage => ({
    ...stage,
    cards: activeCards.value.filter(card => card.stage === stage.id)
  }))
)

const timelineCards = computed(() =>
  activeCards.value
    .slice()
    .sort((left, right) => {
      const leftAnchor = normalizeDate(getTimelineAnchor(left))
      const rightAnchor = normalizeDate(getTimelineAnchor(right))

      if (leftAnchor && rightAnchor) {
        return leftAnchor.getTime() - rightAnchor.getTime()
      }

      return left.project_name.localeCompare(right.project_name, 'ru')
    })
)

const timelineRange = computed(() => {
  const anchors: Date[] = []

  for (const card of timelineCards.value) {
    const start = normalizeDate(card.project_start_date || card.last_writeoff_at || card.created_at)
    const end = normalizeDate(card.project_end_date || card.updated_at || card.last_writeoff_at)

    if (start) {
      anchors.push(start)
    }
    if (end) {
      anchors.push(end)
    }
  }

  if (anchors.length === 0) {
    const today = new Date()
    return {
      start: toLocalDateString(new Date(today.getFullYear(), today.getMonth(), 1)),
      end: toLocalDateString(today)
    }
  }

  anchors.sort((left, right) => left.getTime() - right.getTime())
  return {
    start: toLocalDateString(anchors[0]),
    end: toLocalDateString(anchors[anchors.length - 1])
  }
})

function normalizeDate(value?: string | null) {
  if (!value) {
    return null
  }

  const parsed = parseProjectDateValue(value)
  if (Number.isNaN(parsed.getTime())) {
    return null
  }

  return parsed
}

function toLocalDateString(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function showStatus(type: 'success' | 'warning' | 'error', text: string) {
  statusMessage.value = { type, text }
  setTimeout(() => {
    if (statusMessage.value?.text === text) {
      statusMessage.value = null
    }
  }, 5000)
}

function applyUpdatedCard(updatedCard: ProjectBoardCardRecord) {
  if (!boardData.value) {
    return
  }

  const cards = [...boardData.value.cards]
  const index = cards.findIndex(card => card.project_id === updatedCard.project_id)
  if (index === -1) {
    cards.unshift(updatedCard)
  } else {
    cards.splice(index, 1, updatedCard)
  }

  boardData.value = {
    ...boardData.value,
    cards,
    summary: {
      total_count: cards.length,
      active_count: cards.filter(card => !card.is_archived).length,
      archived_count: cards.filter(card => card.is_archived).length,
      support_count: cards.filter(card => !card.is_archived && card.is_support).length,
      inactive_30_count: cards.filter(card => !card.is_archived && card.stage === 'Нет списаний 1 месяц').length,
      inactive_90_count: cards.filter(card => !card.is_archived && card.stage === 'Нет списаний 3 месяца').length
    }
  }

  if (selectedCard.value?.project_id === updatedCard.project_id) {
    selectedCard.value = updatedCard
  }
}

async function loadBoard(forceRefresh = false) {
  boardData.value = await apiStore.getProjectBoard(forceRefresh)

  if (boardData.value?.warning) {
    showStatus('warning', boardData.value.warning)
  }
}

async function loadMeta(forceRefresh = false) {
  const meta = await apiStore.getProjectBoardMeta(forceRefresh)
  employees.value = meta.employees || []
  companies.value = meta.companies || []
  legalEntities.value = meta.legal_entities || []
}

async function syncBoard(showToast = true) {
  isSyncing.value = true
  try {
    const result = await apiStore.syncProjectCards()
    await Promise.all([
      loadMeta(true),
      loadBoard(true)
    ])

    if (showToast) {
      const baseMessage = `Синхронизировано ${result.synced || 0} проектов. Новых: ${result.created || 0}, обновлено: ${result.updated || 0}.`
      if (result.warning) {
        showStatus('warning', `${baseMessage} ${result.warning}`)
      } else {
        showStatus('success', baseMessage)
      }
    }
  } catch (error) {
    try {
      await loadBoard(true)
    } catch {
      // keep original sync error for global handler
    }
    showStatus('error', 'Не удалось синхронизировать проекты. Попробуйте еще раз или проверьте права приложения в Битрикс24.')
    processErrorGlobal(error)
  } finally {
    isSyncing.value = false
  }
}

async function runDailyCheck() {
  isSyncing.value = true
  try {
    const result = await apiStore.runProjectBoardDailyCheck()
    await loadBoard(true)
    showStatus(
      'success',
      `Проверено ${result.checked || 0} проектов. В 30 дней: ${result.moved_to_30_days || 0}, в 90 дней: ${result.moved_to_90_days || 0}, возвращено в работу: ${result.returned_to_work || 0}.`
    )
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSyncing.value = false
  }
}

function openCard(card: ProjectBoardCardRecord) {
  selectedCard.value = card
  isDrawerOpen.value = true
}

function closeDrawer() {
  isDrawerOpen.value = false
}

function handleDragStart(projectId: string) {
  draggedProjectId.value = projectId
}

async function handleDropCard(payload: { projectId: string; stage: string }) {
  if (!payload.projectId || !payload.stage) {
    return
  }

  const currentCard = allCards.value.find(card => card.project_id === payload.projectId)
  draggedProjectId.value = null

  if (!currentCard || currentCard.stage === payload.stage) {
    return
  }

  try {
    const response = await apiStore.updateProjectStage(payload.projectId, payload.stage)
    if (response.card) {
      applyUpdatedCard(response.card)
      showStatus('success', `Проект переведен в статус «${payload.stage}».`)
    }
  } catch (error) {
    processErrorGlobal(error)
  }
}

async function handleSaveProject(payload: Record<string, any>) {
  isSaving.value = true
  try {
    const response = await apiStore.updateProjectCard(payload)
    if (response.card) {
      applyUpdatedCard(response.card)
    }

    if (response.warning) {
      showStatus('warning', response.warning)
    } else {
      showStatus('success', 'Карточка проекта обновлена.')
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSaving.value = false
  }
}

async function handleArchiveProject(nextArchivedState: boolean) {
  if (!selectedCard.value) {
    return
  }

  isArchiving.value = true
  try {
    const response = await apiStore.archiveProject(selectedCard.value.project_id, nextArchivedState)
    if (response.card) {
      applyUpdatedCard(response.card)
    }

    if (response.warning) {
      showStatus('warning', response.warning)
    } else {
      showStatus('success', nextArchivedState ? 'Проект отправлен в архив.' : 'Проект возвращен из архива.')
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isArchiving.value = false
  }
}

onMounted(async () => {
  isLoading.value = true
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Управление проектами')
    isInit.value = true

    await Promise.all([
      loadMeta(),
      loadBoard()
    ])
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="flex min-h-screen flex-col gap-4 p-4">
    <div class="mb-1">
      <B24Button label="Назад" color="link" @click="router.push('/')" />
    </div>

    <B24Card v-if="isInit">
      <template #header>
        <div class="flex w-full flex-col gap-5">
          <div class="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
            <div>
              <ProseH2>Управление проектами</ProseH2>
              <p class="mt-1 text-xs text-gray-500">
                Доска стадий, архив проектов, локальные поля и контроль нетиповых статусов по списаниям
              </p>
            </div>

            <div class="flex flex-wrap gap-2">
              <B24Button label="Синхронизировать проекты" color="success" :loading="isSyncing" @click="syncBoard()" />
              <B24Button label="Проверить статусы" color="default" :loading="isSyncing" @click="runDailyCheck" />
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 xl:grid-cols-5">
            <div class="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div class="text-xs text-gray-400">Активные</div>
              <div class="mt-1 text-2xl font-semibold text-gray-900">{{ boardData?.summary.active_count || 0 }}</div>
            </div>
            <div class="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div class="text-xs text-gray-400">В архиве</div>
              <div class="mt-1 text-2xl font-semibold text-gray-900">{{ boardData?.summary.archived_count || 0 }}</div>
            </div>
            <div class="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div class="text-xs text-gray-400">Support</div>
              <div class="mt-1 text-2xl font-semibold text-gray-900">{{ boardData?.summary.support_count || 0 }}</div>
            </div>
            <div class="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div class="text-xs text-gray-400">Нет списаний 1 месяц</div>
              <div class="mt-1 text-2xl font-semibold text-gray-900">{{ boardData?.summary.inactive_30_count || 0 }}</div>
            </div>
            <div class="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div class="text-xs text-gray-400">Нет списаний 3 месяца</div>
              <div class="mt-1 text-2xl font-semibold text-gray-900">{{ boardData?.summary.inactive_90_count || 0 }}</div>
            </div>
          </div>

          <div class="flex flex-wrap gap-2 rounded-2xl bg-gray-50 p-1.5">
            <button
              type="button"
              :class="[
                'rounded-xl px-4 py-2 text-sm font-medium transition',
                activeView === 'board' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
              ]"
              @click="activeView = 'board'"
            >
              Board
            </button>
            <button
              type="button"
              :class="[
                'rounded-xl px-4 py-2 text-sm font-medium transition',
                activeView === 'timeline' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
              ]"
              @click="activeView = 'timeline'"
            >
              Timeline
            </button>
            <button
              type="button"
              :class="[
                'rounded-xl px-4 py-2 text-sm font-medium transition',
                activeView === 'archive' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
              ]"
              @click="activeView = 'archive'"
            >
              Archive
            </button>
          </div>

          <div class="grid gap-3 xl:grid-cols-[1.2fr_repeat(4,minmax(0,1fr))]">
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Поиск</span>
              <input
                v-model="searchQuery"
                type="text"
                placeholder="Название проекта, компания, юрлицо, куратор"
                class="rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>

            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Тип проекта</span>
              <select
                v-model="supportFilter"
                class="rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
                <option value="all">Все</option>
                <option value="support">Только support</option>
                <option value="delivery">Только delivery</option>
              </select>
            </label>

            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Куратор</span>
              <select
                v-model="curatorFilter"
                class="rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
                <option value="">Все</option>
                <option v-for="employee in employees" :key="employee.id" :value="String(employee.id)">
                  {{ employee.name }}
                </option>
              </select>
            </label>

            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Компания</span>
              <select
                v-model="companyFilter"
                class="rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
                <option value="">Все</option>
                <option v-for="company in companies" :key="company.id" :value="String(company.id)">
                  {{ company.name }}
                </option>
              </select>
            </label>

            <label class="grid gap-1 text-sm">
              <span class="font-medium text-gray-700">Наше юрлицо</span>
              <select
                v-model="legalEntityFilter"
                class="rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
                <option value="">Все</option>
                <option v-for="entity in legalEntities" :key="entity.id" :value="String(entity.id)">
                  {{ entity.name }}
                </option>
              </select>
            </label>
          </div>

          <div
            v-if="statusMessage"
            :class="['rounded-2xl border px-4 py-3 text-sm', messageClass]"
          >
            {{ statusMessage.text }}
          </div>
        </div>
      </template>

      <div v-if="isLoading" class="py-10 text-center text-gray-500">
        Загружаем проекты...
      </div>

      <div v-else-if="!boardData?.cards?.length" class="space-y-3 py-10 text-center">
        <div class="text-gray-500">Проекты еще не синхронизированы.</div>
        <B24Button label="Синхронизировать сейчас" color="success" :loading="isSyncing" @click="syncBoard()" />
      </div>

      <div v-else-if="activeView === 'board'" class="overflow-x-auto pb-2">
        <div class="grid min-w-max grid-flow-col gap-4">
          <ProjectBoardColumn
            v-for="stage in stageColumns"
            :key="stage.id"
            :title="stage.title"
            :stage="String(stage.id)"
            :cards="stage.cards"
            :can-drop="stage.can_drop"
            @edit="openCard"
            @dragstart="handleDragStart"
            @drop-card="handleDropCard"
          />
        </div>
      </div>

      <div v-else-if="activeView === 'timeline'" class="space-y-4">
        <div class="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
          Диапазон: {{ formatProjectDate(timelineRange.start) }} - {{ formatProjectDate(timelineRange.end) }}
        </div>

        <ProjectTimelineLane
          v-for="card in timelineCards"
          :key="card.project_id"
          :card="card"
          :range-start="timelineRange.start"
          :range-end="timelineRange.end"
          @open="openCard"
        />
      </div>

      <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="card in archivedCards"
          :key="card.project_id"
          type="button"
          class="rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md"
          @click="openCard(card)"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-sm font-semibold text-gray-900">{{ card.project_name }}</div>
              <div class="mt-1 text-xs text-gray-500">
                {{ card.company_name || 'Без компании' }} · {{ card.curator_name || 'Без куратора' }}
              </div>
              <div class="mt-1 text-xs text-gray-400">
                {{ card.our_legal_entity_name || 'Юрлицо не выбрано' }}
              </div>
            </div>
            <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
              Архив
            </span>
          </div>
          <div class="mt-4 text-xs text-gray-500">
            Перенесен в архив: {{ card.archived_at ? formatProjectDate(card.archived_at) : 'локально' }}
          </div>
        </button>

        <div
          v-if="archivedCards.length === 0"
          class="col-span-full rounded-2xl border border-dashed border-gray-200 px-4 py-10 text-center text-gray-400"
        >
          Архивных проектов по текущим фильтрам нет.
        </div>
      </div>
    </B24Card>

    <ProjectBoardDrawer
      v-model="isDrawerOpen"
      :card="selectedCard"
      :employees="employees"
      :companies="companies"
      :legal-entities="legalEntities"
      :is-saving="isSaving"
      :is-archiving="isArchiving"
      @save="handleSaveProject"
      @archive="handleArchiveProject"
    />
  </div>
</template>
