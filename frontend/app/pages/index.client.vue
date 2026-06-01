<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import { buildReportRouteLocation, type ReportRouteName, type ReportRoutePayload } from '~/utils/reportNavigation'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import { openProjectGroup } from '~/utils/openProjectGroup'
import { openCrmItemCard } from '~/utils/openCrmItem'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'

const { t, locales: localesI18n, setLocale } = useI18n()
const router = useRouter()

useHead({
  title: t('page.index.seo.title'),
  script: [
    {
      src: 'https://api.bitrix24.com/api/v1/',
      async: true,
      defer: true
    }
  ]
})

const { initApp, processErrorGlobal } = useAppInit('IndexPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const fieldConfigStore = useFieldConfigStore()

const isInit = ref(false)
const isPortfolioLoading = ref(false)
const portfolioData = ref<any | null>(null)
const projectSearch = ref('')
const selectedProjectId = ref('')

// --- Drawer state ---
const isDrawerOpen = ref(false)
const drawerCard = ref<ProjectBoardCardRecord | null>(null)
const isSaving = ref(false)
const isArchiving = ref(false)
const employeeDirectory = ref<ProjectBoardDirectoryOption[]>([])
const companyDirectory = ref<ProjectBoardDirectoryOption[]>([])
const legalEntityDirectory = ref<ProjectBoardDirectoryOption[]>([])

type AppSection = {
  id: string
  title: string
  description: string
  toneClass: string
  action: () => void
}

const appSections = computed<AppSection[]>(() => [
  {
    id: 'report-project',
    title: 'Отчет по проектам',
    description: 'Сводка по проектам',
    toneClass: 'bg-indigo-50 text-indigo-700',
    action: () => openReport('project')
  },
  {
    id: 'report-project-task',
    title: 'Учет по проектам/задачам',
    description: 'Проект → Задача → Сотрудник',
    toneClass: 'bg-teal-50 text-teal-700',
    action: () => openReport('project-task')
  },
  {
    id: 'report-employee',
    title: 'Отчет по сотрудникам',
    description: 'Детальный отчет по часам',
    toneClass: 'bg-blue-50 text-blue-700',
    action: () => openReport('employee')
  },
  {
    id: 'report-daily',
    title: 'Ежедневная нагрузка',
    description: 'Матрица часов по дням',
    toneClass: 'bg-orange-50 text-orange-700',
    action: () => openReport('daily')
  },
  {
    id: 'report-revenue',
    title: 'Потери выручки',
    description: 'Неучитываемые зоны',
    toneClass: 'bg-rose-50 text-rose-700',
    action: () => openReport('revenue-leakage')
  },
  {
    id: 'report-discipline',
    title: 'Дисциплина времени',
    description: 'Скорость внесения записей',
    toneClass: 'bg-amber-50 text-amber-700',
    action: () => openReport('time-discipline')
  },
  {
    id: 'report-focus',
    title: 'Фокус и распыление',
    description: 'Распределение часов',
    toneClass: 'bg-cyan-50 text-cyan-700',
    action: () => openReport('focus-analysis')
  },
])

function mergeSelectOptions(...groups: Array<ProjectBoardDirectoryOption[]>) {
  const seenIds = new Set<string>()
  const result: ProjectBoardDirectoryOption[] = []
  for (const group of groups) {
    for (const option of group || []) {
      const optionId = String(option.id || '').trim()
      const optionName = String(option.name || '').trim()
      if (!optionId || seenIds.has(optionId)) {
        continue
      }
      seenIds.add(optionId)
      result.push({
        ...option,
        id: optionId,
        name: optionName || optionId,
        inn: option.inn || null,
        search_text: [optionName || optionId, option.inn || '', option.search_text || ''].join(' ').trim()
      })
    }
  }
  return result.sort((left, right) => String(left.name).localeCompare(String(right.name), 'ru'))
}

function buildOptionsFromPortfolioCards(
  idGetter: (card: ProjectBoardCardRecord) => string | null | undefined,
  nameGetter: (card: ProjectBoardCardRecord) => string | null | undefined
) {
  const seenIds = new Set<string>()
  const result: ProjectBoardDirectoryOption[] = []
  const cards = (portfolioData.value?.cards || []) as ProjectBoardCardRecord[]
  for (const card of cards) {
    const optionId = String(idGetter(card) || '').trim()
    const optionName = String(nameGetter(card) || '').trim()
    if (!optionId || seenIds.has(optionId)) {
      continue
    }
    seenIds.add(optionId)
    result.push({ id: optionId, name: optionName || optionId, search_text: optionName || optionId })
  }
  return result
}

const drawerEmployeeOptions = computed(() =>
  mergeSelectOptions(
    employeeDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.curator_user_id,
      card => card.curator_name
    )
  )
)

const drawerCompanyOptions = computed(() =>
  mergeSelectOptions(
    companyDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.company_id,
      card => card.company_name
    )
  )
)

const drawerLegalEntityOptions = computed(() =>
  mergeSelectOptions(
    legalEntityDirectory.value,
    buildOptionsFromPortfolioCards(
      card => card.our_legal_entity_id,
      card => card.our_legal_entity_name
    )
  )
)

const activePortfolioCards = computed<ProjectBoardCardRecord[]>(() => {
  const cards = (portfolioData.value?.cards || []) as ProjectBoardCardRecord[]
  const query = projectSearch.value.trim().toLowerCase()

  return cards
    .filter(card => !card.is_archived)
    .filter((card) => {
      if (!query) {
        return true
      }
      return [
        card.project_name,
        card.company_name,
        card.curator_name,
        card.stage,
        card.project_id,
      ].some(value => String(value || '').toLowerCase().includes(query))
    })
    .sort((left, right) => {
      const leftWeight = Number(left.last_writeoff_days || 0)
      const rightWeight = Number(right.last_writeoff_days || 0)
      return rightWeight - leftWeight
    })
})

const selectedProject = computed<ProjectBoardCardRecord | null>(() => {
  const cards = activePortfolioCards.value
  if (!cards.length) {
    return null
  }

  const current = cards.find(card => card.project_id === selectedProjectId.value)
  return current || cards[0]
})

const summary = computed(() => portfolioData.value?.summary || {
  total_count: 0,
  active_count: 0,
  archived_count: 0,
  support_count: 0,
  inactive_30_count: 0,
  inactive_90_count: 0,
})

watch(
  () => activePortfolioCards.value,
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

function openReport(target: ReportRouteName | ReportRoutePayload) {
  router.push(buildReportRouteLocation(target))
}

function openSettings() {
  router.push('/settings')
}

function openGuide() {
  router.push('/guide')
}

function getStageClass(stage?: string | null) {
  const normalized = String(stage || '')
  if (normalized.includes('Нет списаний 3 месяца')) {
    return 'bg-rose-100 text-rose-700'
  }
  if (normalized.includes('Нет списаний 1 месяц')) {
    return 'bg-amber-100 text-amber-700'
  }
  if (normalized.includes('В просчете')) {
    return 'bg-indigo-100 text-indigo-700'
  }
  if (normalized.includes('В работе')) {
    return 'bg-emerald-100 text-emerald-700'
  }
  return 'bg-slate-100 text-slate-700'
}

async function loadPortfolio(forceRefresh = false) {
  isPortfolioLoading.value = true
  try {
    portfolioData.value = await apiStore.getHomepagePortfolio(forceRefresh)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isPortfolioLoading.value = false
  }
}


function openProject(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || selectedProject.value
  if (!targetCard) {
    return
  }
  openProjectGroup(targetCard.project_id)
}

async function loadMeta() {
  // Best-effort: справочники для карточки проекта не должны рушить главный экран
  try {
    const meta = await apiStore.getProjectBoardMeta()
    const directories = (meta as any).directories || {}
    employeeDirectory.value = directories.employees || (meta as any).employees || []
    companyDirectory.value = directories.companies || (meta as any).companies || []
    legalEntityDirectory.value = directories.legal_entities || (meta as any).legal_entities || []
  } catch (error) {
    console.warn('[IndexPage] Failed to load project board meta (drawer directories)', error)
  }
}

async function openProjectCard(project: ProjectBoardCardRecord | null | undefined) {
  if (!project) {
    return
  }
  drawerCard.value = project
  isDrawerOpen.value = true
  try {
    const detailed = await apiStore.getProjectBoardCard(project.project_id)
    if (detailed) {
      drawerCard.value = detailed
    }
  } catch (error) {
    console.warn('[IndexPage] Failed to load detailed card', error)
  }
}

async function handleSaveProjectCard(payload: Record<string, any>) {
  isSaving.value = true
  try {
    await apiStore.updateProjectCard(payload)
    isDrawerOpen.value = false
    await loadPortfolio(true)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isSaving.value = false
  }
}

async function handleArchiveProjectCard(nextArchivedState: boolean) {
  if (!drawerCard.value) {
    return
  }
  isArchiving.value = true
  try {
    await apiStore.archiveProject(drawerCard.value.project_id, nextArchivedState)
    isDrawerOpen.value = false
    await loadPortfolio(true)
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isArchiving.value = false
  }
}

function openSpa(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || drawerCard.value
  if (!targetCard) {
    return
  }
  const spEntityTypeId = fieldConfigStore.entityTypeId
  const projectItemId = targetCard.project_item_id
  if (spEntityTypeId && projectItemId) {
    openCrmItemCard(spEntityTypeId, projectItemId)
  }
}


function openSelectedProjectReport(report: ReportRouteName = 'project') {
  const card = selectedProject.value
  if (!card) {
    openReport(report)
    return
  }

  openReport({
    report,
    projectId: card.project_id,
    projectName: card.project_name,
    autogenerate: true,
  })
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle(t('page.index.seo.title'))

    // @ts-ignore
    const placementCode = $b24.placement?.title || $b24.placement?.placement || ($b24.placement?.info && $b24.placement.info.placement)
    if (placementCode === 'TASK_VIEW_TAB') {
      router.push('/task')
      return
    }
    if (placementCode === 'SONET_GROUP_DETAIL_TAB') {
      router.push('/reports/project-report')
      return
    }

    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
      // @ts-ignore
      window.BX24.init(() => {
        // @ts-ignore
        const rawPlacement = window.BX24.placement.info()
        if (rawPlacement && rawPlacement.placement === 'TASK_VIEW_TAB') {
          router.push('/task')
        } else if (rawPlacement && rawPlacement.placement === 'SONET_GROUP_DETAIL_TAB') {
          router.push('/reports/project-report')
        }
      })
    }

    isInit.value = true
    await Promise.all([
      loadPortfolio(),
      loadMeta(),
    ])
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <div class="ms-page-shell">
    <div v-if="isInit" class="ms-page-frame space-y-6">
      <section class="ms-surface-hero p-6">
        <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div class="ms-eyebrow">Workspace / Clear Operator</div>
            <h1 class="ms-title mt-2">Рабочее пространство</h1>
            <p class="ms-subtitle mt-2">
              Единая новая главная: список проектов, контекст и переходы во все разделы приложения.
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
              @click="openSettings"
            >
              Настройки
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
              @click="openGuide"
            >
              Юзергайд
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-xl border border-lime-200 bg-lime-50 px-4 py-2 text-sm font-semibold text-lime-700 shadow-sm transition hover:border-lime-300"
              @click="router.push('/projects')"
            >
              Канбан проектов
            </button>
          </div>
        </div>

        <div class="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <article class="ms-stat-card">
            <div class="text-xs text-slate-400">Активные проекты</div>
            <div class="mt-2 text-3xl font-semibold text-slate-900">{{ summary.active_count }}</div>
            <div class="mt-1 text-xs text-slate-500">Портфель в работе</div>
          </article>
          <article class="ms-stat-card">
            <div class="text-xs text-slate-400">Нет списаний 1 месяц</div>
            <div class="mt-2 text-3xl font-semibold text-amber-600">{{ summary.inactive_30_count }}</div>
            <div class="mt-1 text-xs text-slate-500">Требуют внимания</div>
          </article>
          <article class="ms-stat-card">
            <div class="text-xs text-slate-400">Нет списаний 3 месяца</div>
            <div class="mt-2 text-3xl font-semibold text-rose-600">{{ summary.inactive_90_count }}</div>
            <div class="mt-1 text-xs text-slate-500">Высокий риск</div>
          </article>
          <article class="ms-stat-card">
            <div class="text-xs text-slate-400">Support-проекты</div>
            <div class="mt-2 text-3xl font-semibold text-cyan-700">{{ summary.support_count }}</div>
            <div class="mt-1 text-xs text-slate-500">Отдельный режим</div>
          </article>
        </div>
      </section>

      <section class="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <section class="ms-surface p-5">
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Проекты</h2>
              <p class="mt-1 text-sm text-slate-500">Выберите проект и работайте с ним справа.</p>
            </div>
            <label class="grid gap-1 text-sm">
              <span class="font-medium text-slate-700">Поиск проекта</span>
              <input
                v-model="projectSearch"
                type="search"
                placeholder="Название, компания, стадия"
                class="w-full min-w-[250px] rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none transition focus:border-lime-500"
              >
            </label>
          </div>

          <div v-if="isPortfolioLoading" class="ms-empty-state mt-4">
            Загружаем портфель проектов...
          </div>
          <div v-else-if="activePortfolioCards.length === 0" class="ms-empty-state mt-4">
            Проекты не найдены по текущему фильтру.
          </div>
          <div v-else class="mt-4 max-h-[560px] space-y-2 overflow-y-auto pr-1">
            <button
              v-for="card in activePortfolioCards"
              :key="card.project_id"
              type="button"
              class="w-full rounded-2xl border px-4 py-3 text-left transition"
              :class="selectedProject?.project_id === card.project_id
                ? 'border-lime-300 bg-lime-50/40 shadow-sm'
                : 'border-slate-200 bg-white hover:border-slate-300'"
              @click="selectedProjectId = card.project_id"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="truncate text-sm font-semibold text-slate-900">{{ card.project_name }}</div>
                  <div class="mt-1 truncate text-xs text-slate-500">
                    {{ card.company_name || 'Компания не указана' }} · {{ card.curator_name || 'Куратор не указан' }}
                  </div>
                </div>
                <span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold" :class="getStageClass(card.stage)">
                  {{ card.stage }}
                </span>
              </div>
            </button>
          </div>
        </section>

        <aside class="ms-surface p-5">
          <div v-if="selectedProject" class="space-y-4">
            <div class="flex flex-wrap items-center gap-2">
              <span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold" :class="getStageClass(selectedProject.stage)">
                {{ selectedProject.stage }}
              </span>
              <span class="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                ID {{ selectedProject.project_id }}
              </span>
            </div>

            <div>
              <h2 class="text-xl font-semibold text-slate-900">{{ selectedProject.project_name }}</h2>
              <p class="mt-1 text-sm text-slate-500">
                {{ selectedProject.company_name || 'Компания не указана' }} · {{ selectedProject.curator_name || 'Куратор не указан' }}
              </p>
            </div>

            <div class="grid grid-cols-2 gap-2 text-sm">
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div class="text-[11px] uppercase tracking-[0.08em] text-slate-500">Последнее списание</div>
                <div class="mt-1 font-semibold text-slate-900">{{ selectedProject.last_writeoff_days || 0 }} дней назад</div>
              </div>
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div class="text-[11px] uppercase tracking-[0.08em] text-slate-500">Бюджет часов</div>
                <div class="mt-1 font-semibold text-slate-900">{{ selectedProject.project_hours_budget || 'поддержка' }}</div>
              </div>
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div class="text-[11px] uppercase tracking-[0.08em] text-slate-500">Ставка</div>
                <div class="mt-1 font-semibold text-slate-900">{{ selectedProject.hourly_rate || 0 }} ₽</div>
              </div>
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div class="text-[11px] uppercase tracking-[0.08em] text-slate-500">Юрлицо</div>
                <div class="mt-1 font-semibold text-slate-900">{{ selectedProject.our_legal_entity_name || 'Не указано' }}</div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <button type="button" class="ms-action-card text-left" @click="openProject(selectedProject)">
                Открыть проект
                <div class="mt-1 text-xs font-normal text-slate-500">Группа проекта в Bitrix24</div>
              </button>
              <button type="button" class="ms-action-card text-left" @click="openSelectedProjectReport('project')">
                Сформировать отчет
                <div class="mt-1 text-xs font-normal text-slate-500">Отчет по проекту с пресетом</div>
              </button>
              <button type="button" class="ms-action-card text-left" @click="router.push('/projects')">
                Открыть канбан проектов
                <div class="mt-1 text-xs font-normal text-slate-500">Перейти в управление проектами</div>
              </button>
              <button type="button" class="ms-action-card text-left" @click="openProjectCard(selectedProject)">
                Карточка проекта
                <div class="mt-1 text-xs font-normal text-slate-500">Ставка, юрлицо и параметры</div>
              </button>
            </div>
          </div>

          <div v-else class="ms-empty-state">
            Нет доступных проектов для отображения.
          </div>
        </aside>
      </section>

      <section class="ms-surface p-5">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">Рабочие разделы</h2>
            <p class="mt-1 text-sm text-slate-500">
              Ключевые рабочие сценарии на главной. Служебные и настройочные разделы перенесены в «Настройки».
            </p>
          </div>
        </div>
        <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <button
            v-for="section in appSections"
            :key="section.id"
            type="button"
            class="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-sm"
            @click="section.action"
          >
            <div class="inline-flex rounded-full px-2 py-1 text-xs font-semibold" :class="section.toneClass">
              {{ section.title }}
            </div>
            <div class="mt-2 text-sm text-slate-500">{{ section.description }}</div>
          </button>
        </div>
      </section>
    </div>

    <ProjectBoardDrawer
      v-model="isDrawerOpen"
      :card="drawerCard"
      :employees="drawerEmployeeOptions"
      :companies="drawerCompanyOptions"
      :legal-entities="drawerLegalEntityOptions"
      :is-saving="isSaving"
      :is-archiving="isArchiving"
      @save="handleSaveProjectCard"
      @archive="handleArchiveProjectCard"
      @open-project="openProject"
      @open-spa="openSpa"
    />
  </div>
</template>
