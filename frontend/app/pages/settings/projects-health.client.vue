<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import type { ProjectHealthRow } from '~/types/inn'

const router = useRouter()
const apiStore = useApiStore()

useHead({
  title: 'Незаполненные проекты'
})

// region Init
const { initApp, processErrorGlobal } = useAppInit('ProjectsHealthPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null
// endregion

const isInit = ref(false)
const rows = ref<ProjectHealthRow[]>([])
const loadingHealth = ref(false)

const { locales: localesI18n, setLocale } = useI18n()

async function loadHealth() {
  loadingHealth.value = true
  try {
    const res = await apiStore.getProjectsHealth()
    rows.value = res.projects
  } catch (e) {
    processErrorGlobal(e)
  } finally {
    loadingHealth.value = false
  }
}

onMounted(async () => {
  try {
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    isInit.value = true
    await loadHealth()
  } catch (error) {
    processErrorGlobal(error)
  }
})
</script>

<template>
  <B24Container>
    <!-- ms-page-header: заголовок страницы + кнопка «Назад» -->
    <B24PageHeader
      title="Незаполненные проекты"
      description="Проектам не хватает данных для ИНН — список и быстрый переход к исправлению"
    >
      <template #links>
        <B24Button label="Обновить" @click="loadHealth" :loading="loadingHealth" />
        <B24Button label="Назад" color="link" @click="router.push('/settings')" />
      </template>
    </B24PageHeader>

    <!-- ms-surface: основная карточка-контейнер контента -->
    <B24Card v-if="isInit" class="mt-6">
      <!-- ms-empty-state: состояния загрузки и пустого списка -->
      <B24Empty v-if="loadingHealth" title="Загрузка…" size="sm" />
      <B24Empty v-else-if="!rows.length" title="Все проекты заполнены" size="sm" />
      <div v-else class="ms-table-shell mt-4">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50">
            <tr class="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <th class="px-3 py-3">Проект</th>
              <th class="px-3 py-3">Клиент</th>
              <th class="px-3 py-3">Наше юр.лицо</th>
              <th class="px-3 py-3">ИНН клиента</th>
              <th class="px-3 py-3">Наш ИНН</th>
              <th class="px-3 py-3"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="row in rows" :key="row.project_id" class="hover:bg-slate-50">
              <td class="px-3 py-2 font-medium text-slate-800">{{ row.project_name }}</td>
              <td class="px-3 py-2">
                <span v-if="row.has_company" class="text-slate-700">указана</span>
                <span v-else class="inline-flex rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">не указана</span>
              </td>
              <td class="px-3 py-2">
                <span v-if="row.has_legal_entity" class="text-slate-700">указано</span>
                <span v-else class="inline-flex rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">не указано</span>
              </td>
              <td class="px-3 py-2">
                <span v-if="row.client_inn" class="inline-flex rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">{{ row.client_inn }}</span>
                <span v-else-if="row.has_company" class="inline-flex rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">нет в реквизитах</span>
                <span v-else class="text-slate-400">—</span>
              </td>
              <td class="px-3 py-2">
                <span v-if="row.our_inn" class="inline-flex rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">{{ row.our_inn }}</span>
                <span v-else-if="row.has_legal_entity" class="inline-flex rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">нет в реквизитах</span>
                <span v-else class="text-slate-400">—</span>
              </td>
              <td class="px-3 py-2 text-right">
                <B24Button label="Открыть проект" color="link" @click="$router.push({ path: '/projects', query: { search: row.project_id } })" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </B24Card>
  </B24Container>
</template>
