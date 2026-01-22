<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted } from 'vue'
import { SettingsIcon } from '@bitrix24/b24icons-vue/main'
import { BugIcon } from '@bitrix24/b24icons-vue/outline'
import { ActivityIcon } from '@bitrix24/b24icons-vue/main'
import { CrmLettersIcon } from '@bitrix24/b24icons-vue/crm'

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
// endregion ////

const isInit = ref(false)


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
        icon: ActivityIcon,
        title: 'Ежедневная нагрузка',
        description: 'Матрица часов по дням',
        action: () => router.push('/reports/daily'),
        color: 'bg-orange-50 text-orange-600'
    },
    {
        icon: SettingsIcon,
        title: 'Настройки',
        description: 'Настройки приложения',
        action: () => router.push('/settings'),
        color: 'bg-green-50 text-green-600'
    }
]



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

    isInit.value = true
    

  } catch (error) {
    processErrorGlobal(error)
  }
})
// endregion ////
</script>

<template>
  <div class="flex flex-col min-h-screen bg-white w-full justify-center items-center p-6">
      <div v-if="isInit" class="w-full">
          <!-- Header -->
          <div class="mb-10 text-center">
              <h1 class="text-3xl font-bold text-gray-900 mb-2">Выберите отчет</h1>
              <p class="text-gray-500">Доступные отчеты и инструменты управления</p>
              

          </div>

          <!-- Grid -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              <div 
                  v-for="(tile, index) in tiles" 
                  :key="index"
                  @click="tile.action"
                  class="group relative p-8 rounded-xl border border-gray-100 hover:border-gray-200 bg-white shadow-sm hover:shadow-lg transition-all duration-300 cursor-pointer flex flex-col items-center text-center gap-4 h-full"
              >
                  <!-- Icon Box -->
                  <div :class="['p-4 rounded-full transition-colors duration-300', tile.color]">
                      <component :is="tile.icon" class="w-10 h-10" />
                  </div>
                  
                  <!-- Content -->
                  <div class="flex-grow flex flex-col justify-center">
                      <h3 class="text-xl font-semibold text-gray-900 mb-2 group-hover:text-blue-600 transition-colors">
                          {{ tile.title }}
                      </h3>
                      <p class="text-sm text-gray-500">
                          {{ tile.description }}
                      </p>
                  </div>

                  <!-- Arrow (Visual Hint) -->
                  <div class="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity text-gray-300">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                      </svg>
                  </div>
              </div>
          </div>
      </div>




        
  </div>
</template>
