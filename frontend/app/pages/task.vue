<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { resolveTaskPlacementId, useIframeResizeOnToggle } from '@/composables/useTaskPlacement'
import { useTaskTreeLoader } from '@/composables/useTaskTreeLoader'

// --- ICONS ---
// Using Material Symbols directly via class "material-symbols-outlined" 
// assuming they are loaded via nuxt.config head link.

const { t, locales: localesI18n, setLocale } = useI18n()
const { $logger, initApp, processErrorGlobal } = useAppInit('TaskPage')
const { $initializeB24Frame } = useNuxtApp()

let $b24: null | B24Frame = null

// --- STATE ---
const isInit = ref(false)
const initError = ref<string | null>(null)

const rootTaskId = ref<string | null>(null)
const {
    isLoading,
    error,
    usersMap,
    taskTree,
    config,
    clientHourRate,
    loadConfigAndUsers,
    loadTaskTree
} = useTaskTreeLoader()

// Modals
const editingItem = ref<any>(null)
const isReportModalOpen = ref(false)
const isReporting = ref(false)

useIframeResizeOnToggle(isReportModalOpen)
useIframeResizeOnToggle(computed(() => Boolean(editingItem.value)))

// --- INIT LOGIC ---

onMounted(async () => {
    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)
        
        // 1. Get Placement Info
        // Check if we are in a placement
        console.log('TaskPage: $b24.placement', $b24.placement);
        
        // Try to get options from various sources
        // @ts-ignore
        let options = $b24.placement?.options || ($b24.placement?.info && $b24.placement.info.options);
        
        // Fallback to window.BX24 if options are missing but we expect them
        if (!options && typeof window.BX24 !== 'undefined') {
             try {
                 // @ts-ignore
                 const rawInfo = window.BX24.placement.info();
                 if (rawInfo) options = rawInfo.options;
             } catch(e) { console.warn('BX24.placement.info failed', e); }
        }

        const tid = resolveTaskPlacementId($b24)

        if (!tid) {
            // Debug info to help user if it fails
            console.error('TaskPage: No Task ID found. Options:', options);
            error.value = "Не передан ID задачи (options пуст). Откройте приложение во вкладке задачи."
            isLoading.value = false
            return
        }
        rootTaskId.value = tid

        // 2. Load Config & Users
        await loadConfigAndUsers($b24)
        
        // 3. Load Data
        if (config.value?.DEFAULT_SMART_PROCESS_ID && !initError.value) {
            await loadTaskTree($b24, rootTaskId.value!)
        } else if (error.value) {
            initError.value = error.value
        }

        isInit.value = true
    } catch (e: any) {
        processErrorGlobal(e)
        error.value = e.message
        isLoading.value = false
    }
})

// --- ACTIONS ---

async function handleSaveItem(data: any) {
    if (!config.value) return
    const { id, hours, isConsidered, description, employeeId, date } = data
    isLoading.value = true 
    
    try {
        // @ts-ignore
        await $b24.callMethod('crm.item.update', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: id,
            fields: {
                [config.value.FIELDS.HOURS]: hours,
                [config.value.FIELDS.IS_CONSIDERED]: isConsidered ? 'Y' : 'N',
                [config.value.FIELDS.DESCRIPTION]: description,
                [config.value.FIELDS.EMPLOYEE]: employeeId,
                [config.value.FIELDS.DATE]: date
            }
        })
        if (rootTaskId.value) await loadTaskTree($b24!, rootTaskId.value)
    } catch (e: any) {
        alert("Ошибка сохранения: " + e.message)
        isLoading.value = false
    }
    
    editingItem.value = null
}

function handleExportExcel() {
    // Basic CSV export for now as no XLSX lib installed in Nuxt deps yet
    // Or we can assume XLSX is available globally if added to head?
    // Let's implement simple CSV to be safe without external deps
    
    let csvContent = "data:text/csv;charset=utf-8," 
    csvContent += "Type,Title,Employee,Date,Hours Total,Hours Billable,Amount,Comment\n"

    const traverse = (node: any, depth = 0) => {
        const indent = "   ".repeat(depth)
        const row = [
            "Task",
            `"${indent}${node.taskTitle.replace(/"/g, '""')}"`,
            "",
            "",
            node.cumulativeConsidered + node.cumulativeUnconsidered,
            node.cumulativeConsidered,
            node.cumulativeConsidered * clientHourRate.value,
            ""
        ]
        csvContent += row.join(",") + "\n"

        node.items.forEach((item: any) => {
            const iRow = [
                "Item",
                `"${indent} - ${item.title}"`,
                item.employeeName,
                new Date(item.createdTime).toLocaleDateString(),
                item.hours,
                item.isConsidered ? item.hours : 0,
                item.isConsidered ? (item.hours * clientHourRate.value) : 0,
                `"${(item.description || '').replace(/"/g, '""')}"`
            ]
            csvContent += iRow.join(",") + "\n"
        })
        node.children.forEach((c: any) => traverse(c, depth + 1))
    }

    taskTree.value.forEach(root => traverse(root))

    const encodedUri = encodeURI(csvContent)
    const link = document.createElement("a")
    link.setAttribute("href", encodedUri)
    link.setAttribute("download", `report_task_${rootTaskId.value}.csv`)
    document.body.appendChild(link)
    link.click()
}

async function handleTransferToReport() {
    isReporting.value = true
    const batch: any = {}
    let count = 0
    
    const collect = (nodes: any[]) => {
        nodes.forEach(node => {
            node.items.forEach((item: any) => {
                if (item.isConsidered && item.hours > 0) {
                    batch[`report_${item.id}`] = {
                        method: 'task.elapseditem.add',
                        params: {
                            TASKID: node.taskId,
                            FIELDS: {
                                SECONDS: Math.round(item.hours * 3600),
                                COMMENT_TEXT: item.description || `Отражение часов: ${item.title}`,
                                USER_ID: item.employeeId
                            }
                        }
                    }
                    count++
                }
            })
            if (node.children) collect(node.children)
        })
    }
    
    collect(taskTree.value)
    
    if (count === 0) {
        alert("Нет данных для переноса (0 учтенных часов).")
        isReporting.value = false
        isReportModalOpen.value = false
        return
    }

    try {
         // @ts-ignore
        await $b24.callBatch(batch)
        alert("Часы успешно перенесены в стандартный отчет Битрикс24!")
    } catch (e: any) {
        alert("Ошибка переноса: " + e.message)
    } finally {
        isReporting.value = false
        isReportModalOpen.value = false
    }
}

</script>

<template>
<div class="ms-page-shell min-h-screen">
    <div class="w-full space-y-5">
        <section class="ms-surface px-5 py-5">
            <div class="ms-page-header-row">
                <div class="flex items-center gap-4">
                    <div class="rounded-2xl bg-lime-100 p-3 text-lime-700">
                        <span class="material-symbols-outlined text-[26px]">schedule</span>
                    </div>
                    <div>
                        <div class="ms-eyebrow">Task Workspace</div>
                        <h1 class="mt-2 text-2xl font-semibold text-slate-900">Отражение часов</h1>
                        <p class="mt-1 text-sm text-slate-500">Учет трудозатрат по иерархии задач без выхода из карточки.</p>
                    </div>
                </div>

                <div class="flex flex-wrap gap-2">
                    <button @click="handleExportExcel" class="task-secondary-btn">
                        <span class="material-symbols-outlined text-lg">download</span>
                        <span>Excel (CSV)</span>
                    </button>
                    <button @click="isReportModalOpen = true" class="task-primary-btn">
                        <span class="material-symbols-outlined text-lg">send</span>
                        <span>В отчет Bitrix24</span>
                    </button>
                </div>
            </div>
        </section>

        <section v-if="isLoading" class="ms-surface px-6 py-14 text-center">
            <div class="mx-auto flex max-w-sm flex-col items-center gap-3 text-slate-500">
                <span class="material-symbols-outlined text-4xl animate-spin text-lime-600">progress_activity</span>
                <div class="text-base font-medium text-slate-700">Загрузка данных задачи</div>
                <div class="text-sm text-slate-500">Получаем дерево подзадач и записи времени.</div>
            </div>
        </section>

        <section v-else-if="initError || error" class="ms-surface px-6 py-10">
            <div class="mx-auto max-w-xl text-center">
                <div class="mx-auto mb-4 inline-flex rounded-2xl bg-rose-100 p-3 text-rose-600">
                    <span class="material-symbols-outlined text-3xl">error</span>
                </div>
                <h2 class="text-xl font-semibold text-slate-900">Не удалось открыть вкладку задачи</h2>
                <p class="mt-3 text-sm leading-6 text-slate-600">{{ initError || error }}</p>
            </div>
        </section>

        <section v-else class="ms-surface overflow-hidden">
            <div class="flex items-center gap-3 border-b border-slate-200 bg-slate-50/80 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                <div class="flex-1 min-w-0">Задача / Запись</div>
                <div class="hidden w-24 text-right md:block">Сумма</div>
                <div class="w-20 text-right">Учтено</div>
                <div class="w-24 text-right">Не учтено</div>
            </div>

            <TaskNode
                v-for="node in taskTree"
                :key="node.taskId"
                :node="node"
                :rate="clientHourRate"
                @edit="editingItem = $event"
            />
        </section>
    </div>

    <Teleport to="body">
    <div v-if="editingItem" class="ms-modal-overlay" @click.self="editingItem = null">
        <div class="ms-modal-panel flex w-full max-w-2xl flex-col">
            <div class="ms-modal-header">
                <div>
                    <div class="text-sm font-semibold text-slate-900">Редактирование записи</div>
                    <div class="mt-1 text-xs text-slate-500">Измените сотрудника, часы, дату и описание.</div>
                </div>
                <button @click="editingItem = null" class="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>

            <div class="ms-modal-body space-y-4 overflow-y-auto">
                 <div>
                    <label class="task-field-label">Сотрудник</label>
                    <select v-model="editingItem.employeeId" class="task-field-input w-full">
                        <option v-for="u in usersMap" :key="u.ID" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
                    </select>
                </div>
                <div class="grid gap-4 md:grid-cols-2">
                     <div>
                        <label class="task-field-label">Часы</label>
                        <input type="number" v-model="editingItem.hours" class="task-field-input w-full" step="0.5">
                    </div>
                    <label class="task-toggle">
                        <span class="text-sm font-medium text-slate-700">Учитывать в аналитике</span>
                        <input type="checkbox" v-model="editingItem.isConsidered" class="h-4 w-4 rounded border-slate-300 text-lime-600">
                    </label>
                </div>
                 <div>
                    <label class="task-field-label">Дата</label>
                    <input type="date" v-model="editingItem.date" class="task-field-input w-full">
                </div>
                 <div>
                    <label class="task-field-label">Описание</label>
                    <textarea v-model="editingItem.description" class="task-field-input min-h-28 w-full"></textarea>
                </div>
            </div>

            <div class="ms-modal-footer flex flex-wrap justify-end gap-2">
                <button @click="editingItem = null" class="task-secondary-btn">Отмена</button>
                <button @click="handleSaveItem(editingItem)" class="task-primary-btn">Сохранить</button>
            </div>
        </div>
    </div>
    </Teleport>

    <Teleport to="body">
        <div v-if="isReportModalOpen" class="ms-modal-overlay" @click.self="isReportModalOpen = false">
            <div class="ms-modal-panel flex w-full max-w-lg flex-col text-center">
                <div class="ms-modal-body px-6 py-8">
                    <div class="mx-auto mb-4 inline-flex rounded-2xl bg-lime-100 p-3 text-lime-700">
                        <span class="material-symbols-outlined text-3xl">cloud_upload</span>
                    </div>
                    <h3 class="text-xl font-semibold text-slate-900">Отправить часы в отчет Bitrix24?</h3>
                    <p class="mt-3 text-sm leading-6 text-slate-500">
                        Все учтенные часы будут добавлены в задачи Bitrix24 как отработанное время.
                    </p>
                </div>
                <div class="ms-modal-footer flex flex-wrap justify-center gap-2">
                     <button @click="isReportModalOpen = false" class="task-secondary-btn">Отмена</button>
                     <button @click="handleTransferToReport" :disabled="isReporting" class="task-primary-btn">
                        <span v-if="isReporting" class="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                        <span>{{ isReporting ? 'Отправка...' : 'Подтвердить' }}</span>
                     </button>
                </div>
            </div>
        </div>
    </Teleport>

</div>
</template>

<style scoped>
.task-primary-btn,
.task-secondary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 14px;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 600;
  transition: 180ms ease;
}

.task-primary-btn {
  background: #b7ea2c;
  color: #0f172a;
  box-shadow: 0 8px 20px rgba(183, 234, 44, 0.28);
}

.task-primary-btn:hover:not(:disabled) {
  background: #c7f04f;
}

.task-primary-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.task-secondary-btn {
  border: 1px solid rgba(203, 213, 225, 0.9);
  background: rgba(255, 255, 255, 0.96);
  color: #334155;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
}

.task-secondary-btn:hover {
  border-color: rgba(148, 163, 184, 0.95);
  color: #0f172a;
}

.task-field-label {
  display: block;
  margin-bottom: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.task-field-input {
  border: 1px solid rgba(203, 213, 225, 0.95);
  border-radius: 14px;
  background: #fff;
  padding: 10px 12px;
  font-size: 14px;
  color: #0f172a;
  outline: none;
  transition: 180ms ease;
}

.task-field-input:focus {
  border-color: #84cc16;
  box-shadow: 0 0 0 4px rgba(190, 242, 100, 0.25);
}

.task-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  align-self: end;
  border: 1px solid rgba(203, 213, 225, 0.95);
  border-radius: 16px;
  background: #f8fafc;
  padding: 12px 14px;
}
</style>
