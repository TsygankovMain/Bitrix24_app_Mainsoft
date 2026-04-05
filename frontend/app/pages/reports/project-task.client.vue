<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed, watch } from 'vue'
import { useDashboard } from '@bitrix24/b24ui-nuxt/utils/dashboard'
import MultiSelectFilter from '../../components/common/MultiSelectFilter.vue'
import DateRangeFilter from '../../components/common/DateRangeFilter.vue'
import { openCrmItemCard } from '~/utils/openCrmItem'
import { getCurrentMonthRange } from '~/utils/reportDateRange'
import { readProjectReportPreset } from '~/utils/reportNavigation'

const { t, locales: localesI18n, setLocale } = useI18n()

useHead({
  title: 'Учет по проектам/задачам',
  script: [
    { src: 'https://api.bitrix24.com/api/v1/', defer: true }
  ]
})

// region Init ////
const { $logger, initApp, processErrorGlobal } = useAppInit('ProjectTaskReportPage')
const { $initializeB24Frame } = useNuxtApp()
let $b24: null | B24Frame = null

const apiStore = useApiStore()
const userSettings = useUserSettingsStore()
const route = useRoute()
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
const dateFrom = ref('')
const dateTo = ref('')
const isInit = ref(false)
const hasGenerated = ref(false)
const expandedNodes = ref<Set<string>>(new Set())
const entityTypeId = ref<string | number>(0)

const clickableLabelsEnabled = computed(() => userSettings.configSettings.clickableLabelsEnabled ?? false)

function handleLabelClick(itemIdElem: string | number) {
    if (clickableLabelsEnabled.value && entityTypeId.value) {
        openCrmItemCard(entityTypeId.value, itemIdElem)
    }
}

// Filters State
const filterOptions = ref<{ employees: any[], projects: any[] }>({ employees: [], projects: [] })
const selectedEmployees = ref<(string|number)[]>([])
const selectedProjects = ref<(string|number)[]>([])
const employeeFilterMode = ref<'include' | 'exclude'>('include')
const projectFilterMode = ref<'include' | 'exclude'>('include')

async function fetchFilterOptions() {
    try {
        const [employees, projects] = await Promise.all([
            apiStore.getFilterEmployees(),
            apiStore.getFilterProjects()
        ])
        filterOptions.value = { employees, projects }
    } catch (e) {
        processErrorGlobal(e)
    }
}

function applyProjectPresetFromRoute() {
    const preset = readProjectReportPreset(route.query as Record<string, unknown>)
    if (!preset.projectIds.length) {
        return false
    }

    selectedProjects.value = preset.projectIds
    projectFilterMode.value = 'include'

    if (preset.projectName && !filterOptions.value.projects.some(option => String(option.id) === preset.projectIds[0])) {
        filterOptions.value.projects = [
            { id: preset.projectIds[0], name: preset.projectName },
            ...filterOptions.value.projects,
        ]
    }

    return preset.autogenerate
}

async function syncWithRoutePreset() {
    const shouldAutogenerate = applyProjectPresetFromRoute()
    if (!shouldAutogenerate) {
        return
    }

    hasGenerated.value = false
    reportData.value = []
    await fetchReport()
}

async function fetchReport() {
    isLoading.value = true
    try {
        await apiStore.syncTimesheets()
        reportData.value = await apiStore.getReportProjectTaskEmployee(
            dateFrom.value, 
            dateTo.value, 
            { ids: selectedEmployees.value, mode: employeeFilterMode.value },
            { ids: selectedProjects.value, mode: projectFilterMode.value }
        )
        // All groups collapsed by default
        expandedNodes.value = new Set()
        hasGenerated.value = true
    } catch (e) {
        processErrorGlobal(e)
    } finally {
        isLoading.value = false
    }
}

function toggleNode(nodeKey: string) {
    if (expandedNodes.value.has(nodeKey)) {
        expandedNodes.value.delete(nodeKey)
    } else {
        expandedNodes.value.add(nodeKey)
    }
}

function isExpanded(nodeKey: string) {
    return expandedNodes.value.has(nodeKey)
}

function formatHours(val: number) {
    return val != null ? val.toFixed(2) : '0.00'
}

function formatDate(dateStr: string) {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

// Excel Export
import * as XLSX from 'xlsx'

function handleExportExcel() {
    const exportData: any[] = []
    const rowLevels: number[] = []

    const processProject = (project: any) => {
        exportData.push({
            "Название": project.name,
            "Всего часов": project.total_hours,
            "Учтено": project.billable_hours,
            "Не учтено": project.non_billable_hours
        })
        rowLevels.push(0)

        if (project.children) {
            project.children.forEach((task: any) => processTask(task, 1))
        }
    }

    const processTask = (task: any, level: number) => {
        const indent = "    ".repeat(level)
        exportData.push({
            "Название": indent + task.name,
            "Всего часов": task.total_hours,
            "Учтено": task.billable_hours,
            "Не учтено": task.non_billable_hours
        })
        rowLevels.push(level)

        // Sub-tasks
        if (task.children && task.children.length > 0) {
            task.children.forEach((sub: any) => processTask(sub, level + 1))
        }

        // Employees
        if (task.employees) {
            task.employees.forEach((emp: any) => {
                const empIndent = "    ".repeat(level + 1)
                exportData.push({
                    "Название": empIndent + emp.name,
                    "Всего часов": emp.total_hours,
                    "Учтено": emp.billable_hours,
                    "Не учтено": emp.non_billable_hours
                })
                rowLevels.push(level + 1)

                if (emp.items) {
                    emp.items.forEach((item: any) => {
                        const itemIndent = "    ".repeat(level + 2)
                        exportData.push({
                            "Название": itemIndent + (item.nazvanie_zadachi || item.opisanie || '—'),
                            "Дата": item.data ? formatDate(item.data) : '',
                            "Всего часов": item.kolichestvo_chasov,
                            "Учтено": item.uchitivaem ? item.kolichestvo_chasov : 0,
                            "Не учтено": item.uchitivaem ? 0 : item.kolichestvo_chasov
                        })
                        rowLevels.push(level + 2)
                    })
                }
            })
        }
    }

    reportData.value.forEach(p => processProject(p))

    const worksheet = XLSX.utils.json_to_sheet(exportData)
    worksheet['!cols'] = [
        { wch: 55 },
        { wch: 15 },
        { wch: 15 },
        { wch: 15 },
        { wch: 15 }
    ]

    const rows: any[] = [{ level: 0 }]
    rowLevels.forEach(level => {
        rows.push({ level, hidden: false })
    })
    worksheet['!rows'] = rows

    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, "Проект-Задача")
    XLSX.writeFile(workbook, `Report_Project_Task_${dateFrom.value}_${dateTo.value}.xlsx`)
}

// region Lifecycle Hooks ////
onMounted(async () => {
  try {
    isLoading.value = true
    $b24 = await $initializeB24Frame()
    await initApp($b24, localesI18n, setLocale)
    await $b24.parent.setTitle('Учет по проектам/задачам') 
    isInit.value = true
    
    await fetchFilterOptions()
    
    // Load entity type ID for clickable labels
    try {
      const cfg = await apiStore.getConfiguration()
      if (cfg?.sp_entity_type_id) {
        entityTypeId.value = cfg.sp_entity_type_id
      }
    } catch (e) {
      console.warn('Could not load entity type ID:', e)
    }
    
    // Set default range (current month)
    const range = getCurrentMonthRange()
    dateFrom.value = range.dateFrom
    dateTo.value = range.dateTo

    await syncWithRoutePreset()
  } catch (error) {
    processErrorGlobal(error)
  } finally {
    isLoading.value = false
  }
})
// endregion ////

watch(
  () => [
    route.query.project_id,
    route.query.project_ids,
    route.query.project_name,
    route.query.autogenerate
  ],
  async () => {
    if (!isInit.value) {
      return
    }

    await syncWithRoutePreset()
  }
)
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="mb-4">
          <B24Button label="Назад" color="link" @click="$router.push('/')" />
      </div>

      <B24Card v-if="isInit" class="ms-surface">
          <template #header>
            <div class="flex flex-col gap-4 w-full">
                <div class="flex flex-row justify-between items-center w-full">
                    <div>
                      <ProseH2 class="!text-slate-900">Учет по проектам/задачам</ProseH2>
                      <p class="mt-1 text-xs text-slate-500">Группировка: Проект → Задача → Сотрудник → Метки времени</p>
                    </div>
                    <div class="flex gap-2">
                        <B24Button label="Скачать Excel" color="success" @click="handleExportExcel" />
                        <B24Button label="Сформировать" @click="fetchReport" loading-auto />
                    </div>
                </div>
                
                <!-- Filters -->
                <div class="ms-filter-wrap flex flex-wrap gap-4 items-end">
                    <DateRangeFilter 
                        v-model:dateFrom="dateFrom" 
                        v-model:dateTo="dateTo" 
                    />
                    
                    <MultiSelectFilter 
                        label="Сотрудники" 
                        :options="filterOptions.employees" 
                        v-model="selectedEmployees" 
                        v-model:mode="employeeFilterMode"
                    />
                    
                    <MultiSelectFilter 
                        label="Проекты" 
                        :options="filterOptions.projects" 
                        v-model="selectedProjects" 
                        v-model:mode="projectFilterMode"
                    />
                </div>
            </div>
          </template>

          <div v-if="isLoading" class="flex justify-center py-8">
              <span class="text-slate-500">Загрузка...</span>
          </div>
          <div v-else-if="hasGenerated && reportData.length > 0">
              <!-- Table Header -->
              <div class="flex items-center border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <div class="flex-1">Название</div>
                  <div class="w-24 text-right">Всего</div>
                  <div class="w-24 text-right">Учтено</div>
                  <div class="w-24 text-right">Не учтено</div>
              </div>

              <!-- Empty State -->
              <div v-if="reportData.length === 0" class="ms-empty-state">
                  Нет данных за выбранный период
              </div>

              <!-- Project Nodes -->
              <div v-for="project in reportData" :key="'p-' + project.id" class="border-b border-slate-100">
                  <!-- Project Row -->
                  <div 
                      class="flex cursor-pointer items-center bg-lime-50/50 px-4 py-3 transition-colors hover:bg-lime-100/60"
                      @click="toggleNode('project-' + project.id)"
                  >
                      <div class="flex items-center gap-2 flex-1 min-w-0">
                          <span class="text-sm text-slate-400 transition-transform" :class="isExpanded('project-' + project.id) ? 'rotate-90' : ''">▶</span>
                          <span class="text-sm text-lime-700">📁</span>
                          <span class="truncate text-sm font-semibold text-slate-900">{{ project.name }}</span>
                      </div>
                      <div class="w-24 text-right text-sm font-bold text-slate-900">{{ formatHours(project.total_hours) }}</div>
                      <div class="w-24 text-right text-sm font-medium text-emerald-600">{{ formatHours(project.billable_hours) }}</div>
                      <div class="w-24 text-right text-sm font-medium text-rose-500">{{ formatHours(project.non_billable_hours) }}</div>
                  </div>

                  <!-- Tasks -->
                  <div v-if="isExpanded('project-' + project.id) && project.children">
                      <div v-for="task in project.children" :key="'t-' + task.id" class="border-t border-slate-100">
                          <!-- Task Row -->
                          <div 
                              class="flex cursor-pointer items-center px-4 py-2.5 pl-10 transition-colors hover:bg-slate-50"
                              @click="toggleNode('task-' + project.id + '-' + task.id)"
                          >
                              <div class="flex items-center gap-2 flex-1 min-w-0">
                                  <span class="text-xs text-slate-400 transition-transform" :class="isExpanded('task-' + project.id + '-' + task.id) ? 'rotate-90' : ''">▶</span>
                                  <span class="text-sm">📋</span>
                                  <span class="truncate text-sm font-medium text-slate-700">{{ task.name }}</span>
                                  <span v-if="task.children && task.children.length > 0" class="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">подзадачи</span>
                              </div>
                              <div class="w-24 text-right text-sm font-semibold text-slate-700">{{ formatHours(task.total_hours) }}</div>
                              <div class="w-24 text-right text-sm text-emerald-600">{{ formatHours(task.billable_hours) }}</div>
                              <div class="w-24 text-right text-sm text-rose-500">{{ formatHours(task.non_billable_hours) }}</div>
                          </div>

                          <!-- Task expanded content -->
                          <div v-if="isExpanded('task-' + project.id + '-' + task.id)">
                              <!-- Sub-tasks (children of task) -->
                              <div v-if="task.children && task.children.length > 0">
                                  <div v-for="subtask in task.children" :key="'st-' + subtask.id" class="border-t border-slate-100/70">
                                      <div 
                                          class="flex cursor-pointer items-center px-4 py-2 pl-16 transition-colors hover:bg-slate-50"
                                          @click="toggleNode('subtask-' + project.id + '-' + task.id + '-' + subtask.id)"
                                      >
                                          <div class="flex items-center gap-2 flex-1 min-w-0">
                                              <span class="text-xs text-slate-400 transition-transform" :class="isExpanded('subtask-' + project.id + '-' + task.id + '-' + subtask.id) ? 'rotate-90' : ''">▶</span>
                                              <span class="text-xs">↳</span>
                                              <span class="truncate text-sm text-slate-600">{{ subtask.name }}</span>
                                              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">Подзадача</span>
                                          </div>
                                          <div class="w-24 text-right text-sm text-slate-600">{{ formatHours(subtask.total_hours) }}</div>
                                          <div class="w-24 text-right text-sm text-emerald-600">{{ formatHours(subtask.billable_hours) }}</div>
                                          <div class="w-24 text-right text-sm text-rose-500">{{ formatHours(subtask.non_billable_hours) }}</div>
                                      </div>

                                      <!-- Sub-task employees -->
                                      <div v-if="isExpanded('subtask-' + project.id + '-' + task.id + '-' + subtask.id) && subtask.employees">
                                          <div v-for="emp in subtask.employees" :key="'se-' + emp.id" class="border-t border-slate-100/60">
                                              <div 
                                                  class="flex cursor-pointer items-center px-4 py-2 pl-24 transition-colors hover:bg-slate-50"
                                                  @click="toggleNode('semp-' + subtask.id + '-' + emp.id)"
                                              >
                                                  <div class="flex items-center gap-2 flex-1 min-w-0">
                                                      <span class="text-xs text-slate-400 transition-transform" :class="isExpanded('semp-' + subtask.id + '-' + emp.id) ? 'rotate-90' : ''">▶</span>
                                                      <span class="text-sm">👤</span>
                                                      <span class="text-sm text-slate-600">{{ emp.name }}</span>
                                                  </div>
                                                  <div class="w-24 text-right text-sm text-slate-600">{{ formatHours(emp.total_hours) }}</div>
                                                  <div class="w-24 text-right text-sm text-emerald-600">{{ formatHours(emp.billable_hours) }}</div>
                                                  <div class="w-24 text-right text-sm text-rose-500">{{ formatHours(emp.non_billable_hours) }}</div>
                                              </div>
                                              <!-- Sub-task employee items -->
                                              <div v-if="isExpanded('semp-' + subtask.id + '-' + emp.id) && emp.items">
                                                  <div v-for="item in emp.items" :key="'si-' + item.id_zadachi" class="flex items-center border-t border-slate-100/60 bg-slate-50/60 px-4 py-1.5 pl-32">
                                                      <div class="flex items-center gap-2 flex-1 min-w-0">
                                                          <span class="text-xs text-slate-400">🕐</span>
                                                          <span v-if="clickableLabelsEnabled && entityTypeId && item.id_elem" @click.stop="handleLabelClick(item.id_elem)" class="cursor-pointer text-xs text-lime-700 hover:text-lime-800 hover:underline">{{ item.opisanie || item.nazvanie_zadachi || '—' }}</span>
                                                          <span v-else class="text-xs text-slate-500">{{ item.opisanie || item.nazvanie_zadachi || '—' }}</span>
                                                          <span class="text-xs text-slate-400">— {{ formatDate(item.data) }}</span>
                                                      </div>
                                                      <div class="w-24 text-right text-xs text-slate-500">{{ formatHours(item.kolichestvo_chasov) }}</div>
                                                      <div class="w-24 text-right text-xs" :class="item.uchitivaem ? 'text-emerald-600' : 'text-slate-400'">{{ item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</div>
                                                      <div class="w-24 text-right text-xs" :class="!item.uchitivaem ? 'text-rose-500' : 'text-slate-400'">{{ !item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</div>
                                                  </div>
                                              </div>
                                          </div>
                                      </div>
                                  </div>
                              </div>

                              <!-- Task-level employees (direct, no sub-tasks) -->
                              <div v-if="task.employees && task.employees.length > 0">
                                  <div v-for="emp in task.employees" :key="'e-' + emp.id" class="border-t border-slate-100/70">
                                      <div 
                                          class="flex cursor-pointer items-center px-4 py-2 pl-16 transition-colors hover:bg-slate-50"
                                          @click="toggleNode('emp-' + task.id + '-' + emp.id)"
                                      >
                                          <div class="flex items-center gap-2 flex-1 min-w-0">
                                              <span class="text-xs text-slate-400 transition-transform" :class="isExpanded('emp-' + task.id + '-' + emp.id) ? 'rotate-90' : ''">▶</span>
                                              <span class="text-sm">👤</span>
                                              <span class="text-sm text-slate-600">{{ emp.name }}</span>
                                          </div>
                                          <div class="w-24 text-right text-sm text-slate-600">{{ formatHours(emp.total_hours) }}</div>
                                          <div class="w-24 text-right text-sm text-emerald-600">{{ formatHours(emp.billable_hours) }}</div>
                                          <div class="w-24 text-right text-sm text-rose-500">{{ formatHours(emp.non_billable_hours) }}</div>
                                      </div>

                                      <!-- Employee items (time entries) -->
                                      <div v-if="isExpanded('emp-' + task.id + '-' + emp.id) && emp.items">
                                          <div v-for="item in emp.items" :key="'i-' + item.id_zadachi" class="flex items-center border-t border-slate-100/60 bg-slate-50/60 px-4 py-1.5 pl-24">
                                              <div class="flex items-center gap-2 flex-1 min-w-0">
                                                  <span class="text-xs text-slate-400">🕐</span>
                                              <span v-if="clickableLabelsEnabled && entityTypeId && item.id_elem" @click.stop="handleLabelClick(item.id_elem)" class="cursor-pointer text-xs text-lime-700 hover:text-lime-800 hover:underline">{{ item.opisanie || item.nazvanie_zadachi || '—' }}</span>
                                              <span v-else class="text-xs text-slate-500">{{ item.opisanie || item.nazvanie_zadachi || '—' }}</span>
                                              <span class="text-xs text-slate-400">— {{ formatDate(item.data) }}</span>
                                              </div>
                                              <div class="w-24 text-right text-xs text-slate-500">{{ formatHours(item.kolichestvo_chasov) }}</div>
                                              <div class="w-24 text-right text-xs" :class="item.uchitivaem ? 'text-emerald-600' : 'text-slate-400'">{{ item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</div>
                                              <div class="w-24 text-right text-xs" :class="!item.uchitivaem ? 'text-rose-500' : 'text-slate-400'">{{ !item.uchitivaem ? formatHours(item.kolichestvo_chasov) : '—' }}</div>
                                          </div>
                                      </div>
                                  </div>
                              </div>
                          </div>
                      </div>
                  </div>
              </div>

              <!-- Grand Total -->
              <div v-if="reportData.length > 0" class="flex items-center border-t-2 border-slate-300 bg-slate-100 px-4 py-3 text-sm font-bold">
                  <div class="flex-1 text-slate-700">ИТОГО</div>
                  <div class="w-24 text-right text-slate-800">{{ formatHours(reportData.reduce((s: number, p: any) => s + p.total_hours, 0)) }}</div>
                  <div class="w-24 text-right text-emerald-700">{{ formatHours(reportData.reduce((s: number, p: any) => s + p.billable_hours, 0)) }}</div>
                  <div class="w-24 text-right text-rose-600">{{ formatHours(reportData.reduce((s: number, p: any) => s + p.non_billable_hours, 0)) }}</div>
              </div>
          </div>
          <div v-else-if="hasGenerated" class="ms-empty-state">
              Нет данных
          </div>
          <div v-else class="ms-empty-state">
              Выберите фильтры и нажмите «Сформировать»
          </div>
      </B24Card>
    </div>
  </div>
</template>
