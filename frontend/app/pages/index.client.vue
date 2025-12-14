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
  title: t('page.index.seo.title')
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
        icon: BugIcon,
        title: 'Сырые данные (БД)',
        description: 'Проверка синхронизации и данных',
        action: () => router.push('/reports/raw-data'),
        color: 'bg-gray-50 text-gray-600'
    },
    {
        icon: SettingsIcon,
        title: 'Настройки',
        description: 'Настройки приложения',
        action: () => { 
            alert('Settings coming soon')
        },
        color: 'bg-green-50 text-green-600'
    },
    {
        icon: BugIcon,
        title: 'Обратная связь',
        description: 'Сообщить об ошибке или идее',
        action: () => { alert('Форма обратной связи в разработке') },
        color: 'bg-purple-50 text-purple-600'
    }
]

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle(t('page.index.seo.title'))
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
