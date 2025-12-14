<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import ProjectEmployeeTable from '../../components/reports/ProjectEmployeeTable.vue'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Отчет по проектам'
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('ProjectReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
// endregion ////

const { contextId, isLoading: isLoadingState, load } = useDashboard({ isLoading: ref(false), load: () => {} })
const isLoading = computed({
  get: () => isLoadingState?.value === true,
  set: (value: boolean) => {
    load?.(value, contextId)
  }
})

// Report State
const reportData = ref<any[]>([])
const dateFrom = ref('') // YYYY-MM-DD
const isInit = ref(false)

async function fetchReport() {
    isLoading.value = true
    try {
        reportData.value = await apiStore.getReportProjectEmployee(dateFrom.value)
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Отчет по проектам') 
    isInit.value = true
    
    // Initial fetch
    await fetchReport()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
// endregion ////
</script>

<template>
  <div class="flex flex-col gap-4 p-4 min-h-screen">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit">
          <template #header>
            <div class="flex flex-row justify-between items-center w-full">
                <ProseH2>Отчет по проектам</ProseH2>
                <div class="flex gap-2 items-center">
                    <input type="date" v-model="dateFrom" class="border rounded px-2 py-1 outline-none focus:ring-2 focus:ring-blue-500" @change="fetchReport" />
                    <B24Button label="Обновить" @click="fetchReport" loading-auto />
                </div>
            </div>
          </template>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-gray-500">Загрузка...</span>
          </div>
          <div v-else>
              <ProjectEmployeeTable :data="reportData" />
          </div>
      </B24Card>
  </div>
</template>
