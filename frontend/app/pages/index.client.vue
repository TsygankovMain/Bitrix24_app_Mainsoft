<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, onMounted, ref } from 'vue'
import { SettingsIcon } from '@bitrix24/b24icons-vue/main'
import { BugIcon } from '@bitrix24/b24icons-vue/outline'
import { ActivityIcon } from '@bitrix24/b24icons-vue/main'
import { CrmLettersIcon } from '@bitrix24/b24icons-vue/crm'
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'
import PortfolioHomeDashboard from '~/components/home/PortfolioHomeDashboard.vue'
import { buildReportRouteLocation, type ReportRouteName, type ReportRoutePayload } from '~/utils/reportNavigation'

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

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('IndexPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const userSettings = useUserSettingsStore()
// endregion ////

const isInit = ref(false)
const isPortfolioLoading = ref(false)
const portfolioData = ref<any | null>(null)
const homePageMode = ref<'legacy' | 'portfolio'>('legacy')
const isSupportLoading = ref(false)
const supportStatus = ref<any | null>(null)


// Tiles Configuration
// Tiles Configuration
const tiles = [
    {
        icon: ActivityIcon,
        title: 'Отчет по сотрудникам',
        description: 'Детальный отчет по часам сотрудников',
        action: () => router.push('/reports/employee'),
        color: 'bg-blue-50 text-blue-600'
    },
    {
        icon: CrmLettersIcon,
        title: 'Отчет по проектам',
        description: 'Сводка по проектам',
        action: () => router.push('/reports/project'), 
        color: 'bg-indigo-50 text-indigo-600'
    },
    {
        icon: CrmLettersIcon,
        title: 'Управление проектами',
        description: 'Board, таймлайн и архив проектов',
        action: () => router.push('/projects'),
        color: 'bg-lime-50 text-lime-700'
    },
    {
        icon: ActivityIcon,
        title: 'Ежедневная нагрузка',
        description: 'Матрица часов по дням',
        action: () => router.push('/reports/daily'),
        color: 'bg-orange-50 text-orange-600'
    },
    {
        icon: CrmLettersIcon,
        title: 'Учет по проектам/задачам',
        description: 'Проект → Задача → Сотрудник → Метки',
        action: () => router.push('/reports/project-task'),
        color: 'bg-teal-50 text-teal-600'
    },
    {
        icon: ActivityIcon,
        title: 'Потери выручки',
        description: 'Где копятся неучтенные часы',
        action: () => router.push('/reports/revenue-leakage'),
        color: 'bg-red-50 text-red-600'
    },
    {
        icon: BugIcon,
        title: 'Дисциплина времени',
        description: 'Насколько быстро вносятся записи',
        action: () => router.push('/reports/time-discipline'),
        color: 'bg-amber-50 text-amber-700'
    },
    {
        icon: BookOpen1Icon,
        title: 'Фокус и распыление',
        description: 'Распределение часов по проектам',
        action: () => router.push('/reports/focus-analysis'),
        color: 'bg-cyan-50 text-cyan-700'
    },
    {
        icon: SettingsIcon,
        title: 'Настройки',
        description: 'Настройки приложения',
        action: () => router.push('/settings'),
        color: 'bg-green-50 text-green-600'
    },
    {
        icon: BookOpen1Icon,
        title: 'Юзергайд',
        description: 'Инструкция и описание полей',
        action: () => router.push('/guide'),
        color: 'bg-purple-50 text-purple-600'
    }
]

const homeModeLabel = computed(() =>
  homePageMode.value === 'portfolio' ? 'Новый формат' : 'Старый формат'
)

const supportDotClass = computed(() => {
  if (isSupportLoading.value) {
    return 'bg-amber-400'
  }
  if (supportStatus.value?.status === 'connected') {
    return 'bg-emerald-500'
  }
  if (supportStatus.value?.status === 'error') {
    return 'bg-rose-500'
  }
  return 'bg-slate-300'
})

function openReport(target: ReportRouteName | ReportRoutePayload) {
  router.push(buildReportRouteLocation(target))
}

function openSettings() {
  router.push('/settings')
}

function openGuide() {
  router.push('/guide')
}

async function refreshSupportStatus(forceRefresh = false) {
  try {
    supportStatus.value = await apiStore.getSupportStatus(forceRefresh)
  } catch (error) {
    console.error('Failed to load support status:', error)
  }
}

function openSupportMessenger(dialogId: string) {
  const bx24Global = (window as any)?.BX24
  if (!dialogId || !bx24Global?.im?.openMessenger) {
    return false
  }

  bx24Global.im.openMessenger(`imol|${dialogId}`)
  return true
}

async function openSupport() {
  if (isSupportLoading.value) {
    return
  }

  if (supportStatus.value?.dialog_id && openSupportMessenger(String(supportStatus.value.dialog_id))) {
    return
  }

  if (supportStatus.value?.configured === false) {
    router.push('/guide?support=1')
    return
  }

  isSupportLoading.value = true
  try {
    const result = await apiStore.connectSupportLine()
    supportStatus.value = result

    if (!openSupportMessenger(String(result?.dialog_id || ''))) {
      router.push('/guide?support=1')
    }
  } catch (error) {
    console.error('Failed to open support:', error)
    processErrorGlobal(error)
    router.push('/guide?support=1')
  } finally {
    isSupportLoading.value = false
  }
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

async function setHomePageMode(mode: 'legacy' | 'portfolio') {
  if (homePageMode.value === mode) {
    return
  }

  homePageMode.value = mode
  userSettings.configSettings.homePageMode = mode

  try {
    await userSettings.saveSettings()
  } catch (error) {
    console.error('Failed to save home page mode:', error)
  }

  if (mode === 'portfolio' && !portfolioData.value) {
    await loadPortfolio()
  }
}



// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle(t('page.index.seo.title'))
    
    // Auto-redirect if in Task Tab
    console.log('DEBUG: $b24.placement:', $b24.placement);
    
    // Check JSSDK wrapper properties
    // Based on logs: PlacementManager has #title: 'TASK_VIEW_TAB'. 
    // Trying public getter .title
    // @ts-ignore
    const placementCode = $b24.placement?.title || $b24.placement?.placement || ($b24.placement?.info && $b24.placement.info.placement);
    
    console.log('DEBUG: Resolved Placement Code:', placementCode);
    
    if (placementCode === 'TASK_VIEW_TAB') {
         console.log('DEBUG: Redirecting to /task via JSSDK');
         router.push('/task')
         return 
    }
    
    if (placementCode === 'SONET_GROUP_DETAIL_TAB') {
         console.log('DEBUG: Redirecting to /reports/project-report via JSSDK');
         router.push('/reports/project-report')
         return 
    }
    
    // Fallback: Use Global BX24 with init (Standard Pattern)
    // @ts-ignore
    if (typeof window.BX24 !== 'undefined') {
        // @ts-ignore
        window.BX24.init(() => {
            // @ts-ignore
            const rawPlacement = window.BX24.placement.info();
            console.log('DEBUG: Window Placement Info:', rawPlacement);
             if (rawPlacement && rawPlacement.placement === 'TASK_VIEW_TAB') {
                  console.log('DEBUG: Redirecting to /task via Window');
                  router.push('/task')
             } else if (rawPlacement && rawPlacement.placement === 'SONET_GROUP_DETAIL_TAB') {
                  console.log('DEBUG: Redirecting to /reports/project-report via Window');
                  router.push('/reports/project-report')
             }
        })
    }

    homePageMode.value = userSettings.configSettings.homePageMode === 'portfolio' ? 'portfolio' : 'legacy'
    isInit.value = true
    void refreshSupportStatus()
    if (homePageMode.value === 'portfolio') {
      await loadPortfolio()
    } else {
      void apiStore.getHomepagePortfolio().then((result) => {
        portfolioData.value = result
      }).catch(() => {
        // warm cache silently
      })
    }

  } catch (error) {
    processErrorGlobal(error)
  }
})
// endregion ////
</script>

<template>
  <div class="ms-page-shell">
    <div v-if="isInit" class="ms-page-frame">
      <div class="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 class="ms-title">Рабочее пространство</h1>
          <p class="mt-2 ms-subtitle">
            {{ homePageMode === 'portfolio' ? 'Новая главная сфокусирована на проектном портфеле и сигналах.' : 'Отчеты, управление проектами и служебные разделы.' }}
          </p>
        </div>

        <div class="flex flex-col gap-3 lg:items-end">
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
              class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-lime-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-70"
              :disabled="isSupportLoading"
              @click="openSupport"
            >
              <span :class="['h-2.5 w-2.5 rounded-full', supportDotClass]" />
              {{ isSupportLoading ? 'Подключение...' : 'Поддержка' }}
            </button>
          </div>

          <div class="ms-segmented">
            <button
              type="button"
              :class="[
                'ms-segmented-btn',
                homePageMode === 'legacy' ? 'ms-segmented-btn-active-dark' : '',
              ]"
              @click="setHomePageMode('legacy')"
            >
              Старый
            </button>
            <button
              type="button"
              :class="[
                'ms-segmented-btn',
                homePageMode === 'portfolio' ? 'ms-segmented-btn-active-lime' : '',
              ]"
              @click="setHomePageMode('portfolio')"
            >
              Новый
            </button>
          </div>
        </div>
      </div>

      <div v-if="homePageMode === 'portfolio'">
        <PortfolioHomeDashboard
          :data="portfolioData"
          :loading="isPortfolioLoading"
          @open-board="router.push('/projects')"
          @open-report="openReport"
        />
      </div>

      <div v-else>
        <div class="mb-10 text-center">
          <div class="inline-flex rounded-full bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 shadow-sm">
            {{ homeModeLabel }}
          </div>
          <h2 class="mt-4 text-3xl font-semibold tracking-tight text-slate-900">Выберите инструмент</h2>
          <p class="mt-2 ms-subtitle">Отчеты, управление проектами и служебные разделы</p>
        </div>

        <div class="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="(tile, index) in tiles"
            :key="index"
            @click="tile.action"
            class="ms-surface group relative flex h-full cursor-pointer flex-col items-center gap-4 p-8 text-center transition-all duration-300 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg"
          >
            <div :class="['rounded-full p-4 transition-colors duration-300', tile.color]">
              <component :is="tile.icon" class="h-10 w-10" />
            </div>

            <div class="flex flex-grow flex-col justify-center">
              <h3 class="mb-2 text-xl font-semibold text-slate-900 transition-colors group-hover:text-lime-700">
                {{ tile.title }}
              </h3>
              <p class="text-sm text-slate-500">
                {{ tile.description }}
              </p>
            </div>

            <div class="absolute right-4 top-4 text-slate-300 opacity-0 transition-opacity group-hover:opacity-100">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
