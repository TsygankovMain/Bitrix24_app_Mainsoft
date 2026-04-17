<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref, watch } from 'vue'
import ProjectBoardDrawer from '~/components/projects/ProjectBoardDrawer.vue'
import { buildReportRouteLocation, type ReportRouteName, type ReportRoutePayload } from '~/utils/reportNavigation'
import type { ProjectBoardCardRecord, ProjectBoardDirectoryOption } from '~/utils/projectBoard'
import { openProjectGroup } from '~/utils/openProjectGroup'

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

const isInit = ref(false)
const isPortfolioLoading = ref(false)
const portfolioData = ref<any | null>(null)
const projectSearch = ref('')
const selectedProjectId = ref('')
const isHomeProjectDrawerOpen = ref(false)
const selectedHomeProject = ref<ProjectBoardCardRecord | null>(null)
const isHomeProjectSaving = ref(false)
const isHomeProjectArchiving = ref(false)
const homeEmployeeDirectory = ref<ProjectBoardDirectoryOption[]>([])
const homeCompanyDirectory = ref<ProjectBoardDirectoryOption[]>([])
const homeLegalEntityDirectory = ref<ProjectBoardDirectoryOption[]>([])

type AppSection = {
  id: string
  title: string
  description: string
  toneClass: string
  action: () => void
}

const appSections = computed<AppSection[]>(() => [
  {
    id: 'task-workspace',
    title: 'Учет часов в задаче',
    description: 'Рабочее место трудозатрат',
    toneClass: 'bg-sky-50 text-sky-700',
    action: () => router.push('/task')
  },
  {
    id: 'group-project-report',
    title: 'Проектный отчет (группа)',
    description: 'Сценарий SONET_GROUP_DETAIL_TAB',
    toneClass: 'bg-indigo-50 text-indigo-700',
    action: () => router.push('/reports/project-report')
  },
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
    description: 'Non-billable зоны',
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

async function ensureHomeProjectDirectories(forceRefresh = false) {
  const needsLoad = forceRefresh
    || !homeEmployeeDirectory.value.length
    || !homeCompanyDirectory.value.length
    || !homeLegalEntityDirectory.value.length

  if (!needsLoad) {
    return
  }

  const meta = await apiStore.getProjectBoardMeta(forceRefresh)
  const directories = meta.directories || {}
  homeEmployeeDirectory.value = directories.employees || meta.employees || []
  homeCompanyDirectory.value = directories.companies || meta.companies || []
  homeLegalEntityDirectory.value = directories.legal_entities || meta.legal_entities || []
}

function openHomeProjectCard(card: ProjectBoardCardRecord) {
  selectedHomeProject.value = card
  isHomeProjectDrawerOpen.value = true
  void ensureHomeProjectDirectories()
}

function openProject(card?: ProjectBoardCardRecord | null) {
  const targetCard = card || selectedHomeProject.value || selectedProject.value
  if (!targetCard) {
    return
  }
  openProjectGroup(targetCard.project_id)
}

function applyUpdatedHomeProjectCard(updatedCard: ProjectBoardCardRecord) {
  if (selectedHomeProject.value?.project_id === updatedCard.project_id) {
    selectedHomeProject.value = updatedCard
  }

  if (selectedProjectId.value === updatedCard.project_id) {
    selectedProjectId.value = updatedCard.project_id
  }

  if (!portfolioData.value?.cards) {
    return
  }

  portfolioData.value = {
    ...portfolioData.value,
    cards: portfolioData.value.cards.map((card: ProjectBoardCardRecord) =>
      card.project_id === updatedCard.project_id ? updatedCard : card
    ),
    risk_cards: (portfolioData.value.risk_cards || []).map((card: ProjectBoardCardRecord) =>
      card.project_id === updatedCard.project_id ? updatedCard : card
    ),
  }
}

async function refreshPortfolioAfterProjectChange(updatedCard?: ProjectBoardCardRecord | null) {
  await loadPortfolio(true)

  if (!updatedCard || !portfolioData.value?.cards?.length) {
    return
  }

  const nextCard = portfolioData.value.cards.find((card: ProjectBoardCardRecord) => card.project_id === updatedCard.project_id)
  if (nextCard) {
    selectedHomeProject.value = nextCard
    selectedProjectId.value = nextCard.project_id
  }
}

async function handleHomeProjectSave(payload: Record<string, any>) {
  isHomeProjectSaving.value = true
  try {
    const response = await apiStore.updateProjectCard(payload)
    if (response.card) {
      applyUpdatedHomeProjectCard(response.card)
      await refreshPortfolioAfterProjectChange(response.card)
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isHomeProjectSaving.value = false
  }
}

async function handleHomeProjectArchive(nextArchivedState: boolean) {
  if (!selectedHomeProject.value) {
    return
  }

  isHomeProjectArchiving.value = true
  try {
    const response = await apiStore.archiveProject(selectedHomeProject.value.project_id, nextArchivedState)
    if (response.card) {
      applyUpdatedHomeProjectCard(response.card)
      await refreshPortfolioAfterProjectChange(response.card)
    } else {
      await refreshPortfolioAfterProjectChange(selectedHomeProject.value)
    }
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isHomeProjectArchiving.value = false
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
    await loadPortfolio()
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
                <div class="mt-1 font-semibold text-slate-900">{{ selectedProject.project_hours_budget || 'support' }}</div>
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
              <button type="button" class="ms-action-card text-left" @click="openHomeProjectCard(selectedProject)">
                Открыть карточку
                <div class="mt-1 text-xs font-normal text-slate-500">Слайдер карточки проекта</div>
              </button>
              <button type="button" class="ms-action-card text-left" @click="openSelectedProjectReport('project')">
                Сформировать отчет
                <div class="mt-1 text-xs font-normal text-slate-500">Отчет по проекту с пресетом</div>
              </button>
              <button type="button" class="ms-action-card text-left" @click="router.push('/projects')">
                Открыть board
                <div class="mt-1 text-xs font-normal text-slate-500">Перейти в управление проектами</div>
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

      <ProjectBoardDrawer
        v-model="isHomeProjectDrawerOpen"
        :card="selectedHomeProject"
        :employees="homeEmployeeDirectory"
        :companies="homeCompanyDirectory"
        :legal-entities="homeLegalEntityDirectory"
        :is-saving="isHomeProjectSaving"
        :is-archiving="isHomeProjectArchiving"
        @save="handleHomeProjectSave"
        @archive="handleHomeProjectArchive"
        @open-project="openProject"
      />
    </div>
  </div>
</template>
