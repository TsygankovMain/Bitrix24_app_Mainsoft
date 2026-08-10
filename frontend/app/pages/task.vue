<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { onMounted, ref, computed } from 'vue'
import { resolveTaskPlacementId, useIframeResizeOnToggle } from '@/composables/useTaskPlacement'
import { useTaskTreeLoader } from '@/composables/useTaskTreeLoader'
import { useTimesheetEntry } from '@/composables/useTimesheetEntry'
import { makeNewEntryDraft } from '~/utils/timesheetEntry'
import type { TaskWorkspaceItem, TaskWorkspaceNode, TaskWorkspaceUser } from '~/types/task-workspace'

// --- ICONS ---
// Using Material Symbols directly via class "material-symbols-outlined" 
// assuming they are loaded via nuxt.config head link.

const { locales: localesI18n, setLocale } = useI18n()
const { initApp, processErrorGlobal } = useAppInit('TaskPage')
const { $initializeB24Frame } = useNuxtApp()
const toast = useToast()

let $b24: null | B24Frame = null

// --- STATE ---
const isInit = ref(false)
const initError = ref<string | null>(null)

const rootTaskId = ref<string | null>(null)
const {
    isLoading,
    error,
    usersMap,
    usersList,
    currentUserId,
    taskTree,
    config,
    clientHourRate,
    loadConfigAndUsers,
    loadTaskTree
} = useTaskTreeLoader()

// Сборка полей списания вместе с проектным контекстом.
const { prepareEntryFields } = useTimesheetEntry()

// Modals
interface EditingItem {
    id: string | number | null
    /** Задача, на которую списываются часы. Пусто у старых записей — тогда корневая. */
    taskId: string
    hours: number
    isConsidered: boolean
    description: string
    employeeId: string | number
    date: string
    [key: string]: unknown
}

const editingItem = ref<EditingItem | null>(null)
/** Создание отличается от правки только отсутствием id — как и в рабочем экране. */
const isCreatingEntry = computed(() => Boolean(editingItem.value) && !editingItem.value?.id)
const isReportModalOpen = ref(false)
const isReporting = ref(false)

useIframeResizeOnToggle(isReportModalOpen)
useIframeResizeOnToggle(computed(() => Boolean(editingItem.value)))

const employeeSelectItems = computed(() =>
    Object.values(usersMap.value as Record<string, TaskWorkspaceUser>).map((u: TaskWorkspaceUser) => ({
        label: `${u.NAME ?? ''} ${u.LAST_NAME ?? ''}`.trim() || String(u.ID),
        value: u.ID,
    }))
)

// --- INIT LOGIC ---

onMounted(async () => {
    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)
        
        // 1. Get Placement Info
        // Check if we are in a placement
        console.log('TaskPage: $b24.placement', $b24.placement);
        
        // Try to get options from various sources
        // @ts-expect-error placement.info is not part of the typed B24Frame surface
        let options = $b24.placement?.options || ($b24.placement?.info && $b24.placement.info.options);
        
        // Fallback to window.BX24 if options are missing but we expect them
        if (!options && typeof window.BX24 !== 'undefined') {
             try {
                 // @ts-expect-error BX24 is injected globally by the Bitrix24 frame and is not typed
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
        // includeProfile: нужен текущий пользователь — он подставляется
        // сотрудником по умолчанию в форму списания.
        await loadConfigAndUsers($b24, { includeProfile: true })
        
        // 3. Load Data
        if (config.value?.DEFAULT_SMART_PROCESS_ID && !initError.value) {
            await loadTaskTree($b24, rootTaskId.value!)
        } else if (error.value) {
            initError.value = error.value
        }

        isInit.value = true
    } catch (e: unknown) {
        processErrorGlobal(e)
        error.value = (e as { message?: string }).message
    } finally {
        // Единственный владелец завершения загрузки: какой бы веткой ни закончился
        // init (нет ID задачи, конфигурация не загрузилась, отказ REST), спиннер гаснет.
        isLoading.value = false
    }
})

// --- ACTIONS ---

/** Открыть форму списания на конкретную задачу дерева. */
function handleCreateEntry(taskId?: string) {
    const targetTaskId = String(taskId || rootTaskId.value || '')
    if (!targetTaskId) {
        toast.add({ title: 'Не удалось определить задачу для списания.', color: 'air-primary-alert' })
        return
    }

    editingItem.value = makeNewEntryDraft({
        taskId: targetTaskId,
        employeeId: currentUserId.value || usersList.value[0]?.ID || '',
        today: new Date()
    }) as EditingItem
}

/**
 * Сохранение записи: создание и правка идут одним путём.
 *
 * Поля собираются вместе с проектным контекстом — иерархия задач, проект, ИНН,
 * снимок ставки часа, привязка к элементу Project SPA. Собирать их нужно и при
 * правке: у записи мог смениться сотрудник или часы, а иерархия и реквизиты
 * хранятся прямо в элементе смарт-процесса — именно по ним потом строится
 * отчётность и выгрузка в 1С. Решения о том, что куда писать и что блокирует
 * сохранение, живут в utils/timesheetEntry.ts и покрыты тестами.
 */
async function handleSaveItem(data: EditingItem) {
    if (!config.value || !$b24) return
    isLoading.value = true

    try {
        const { fields, validation } = await prepareEntryFields(
            $b24,
            config.value,
            {
                ...data,
                taskId: String(data.taskId || rootTaskId.value || ''),
                splitHours: 0,
                keepOriginalConsidered: false
            },
            taskTree.value
        )

        if (validation.warning) {
            console.warn('[TaskPage]', validation.warning)
        }

        if (validation.error) {
            toast.add({ title: validation.error, color: 'air-primary-alert' })
            isLoading.value = false
            return
        }

        if (data.id) {
            await $b24.callMethod('crm.item.update', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                id: data.id,
                fields
            })
        } else {
            await $b24.callMethod('crm.item.add', {
                entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
                fields
            })
        }

        editingItem.value = null
        toast.add({ title: data.id ? 'Запись сохранена' : 'Часы отражены', color: 'air-primary-success' })
        if (rootTaskId.value) await loadTaskTree($b24, rootTaskId.value)
        return
    } catch (e: unknown) {
        toast.add({ title: 'Ошибка сохранения: ' + (e as { message?: string }).message, color: 'air-primary-alert' })
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

    const traverse = (node: TaskWorkspaceNode, depth = 0) => {
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

        node.items.forEach((item: TaskWorkspaceItem) => {
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
        node.children.forEach((c: TaskWorkspaceNode) => traverse(c, depth + 1))
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
    const batch: Record<string, unknown> = {}
    let count = 0

    const collect = (nodes: TaskWorkspaceNode[]) => {
        nodes.forEach(node => {
            node.items.forEach((item: TaskWorkspaceItem) => {
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
        toast.add({ title: "Нет данных для переноса (0 учтенных часов).", color: 'air-primary-alert' })
        isReporting.value = false
        isReportModalOpen.value = false
        return
    }

    try {
         // @ts-expect-error $b24 is guaranteed initialized in onMounted before this handler runs
        await $b24.callBatch(batch)
        toast.add({ title: "Часы успешно перенесены в стандартный отчет Битрикс24!", color: 'air-primary-success' })
    } catch (e: unknown) {
        toast.add({ title: "Ошибка переноса: " + (e as { message?: string }).message, color: 'air-primary-alert' })
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
                    <div class="rounded-2xl bg-blue-100 p-3 text-[#0075ff]">
                        <span class="material-symbols-outlined text-[26px]">schedule</span>
                    </div>
                    <div>
                        <div class="ms-eyebrow">Task Workspace</div>
                        <h1 class="mt-2 text-2xl font-semibold text-slate-900">Отражение часов</h1>
                        <p class="mt-1 text-sm text-slate-500">Учет трудозатрат по иерархии задач без выхода из карточки.</p>
                    </div>
                </div>

                <div class="flex flex-wrap gap-2">
                    <B24Button label="Отразить" color="air-primary" @click="handleCreateEntry()" />
                    <B24Button label="Excel (CSV)" color="default" @click="handleExportExcel" />
                    <B24Button label="В отчет Bitrix24" color="success" @click="isReportModalOpen = true" />
                </div>
            </div>
        </section>

        <!-- Ошибка идёт ПЕРЕД загрузкой: иначе залипший isLoading прячет причину отказа. -->
        <section v-if="initError || error" class="ms-surface px-6 py-10">
            <div class="mx-auto max-w-xl text-center">
                <div class="mx-auto mb-4 inline-flex rounded-2xl bg-rose-100 p-3 text-rose-600">
                    <span class="material-symbols-outlined text-3xl">error</span>
                </div>
                <h2 class="text-xl font-semibold text-slate-900">Не удалось открыть вкладку задачи</h2>
                <p class="mt-3 text-sm leading-6 text-slate-600">{{ initError || error }}</p>
            </div>
        </section>

        <section v-else-if="isLoading" class="ms-surface px-6 py-14 text-center">
            <div class="mx-auto flex max-w-sm flex-col items-center gap-3 text-slate-500">
                <span class="material-symbols-outlined text-4xl animate-spin text-[#0075ff]">progress_activity</span>
                <div class="text-base font-medium text-slate-700">Загрузка данных задачи</div>
                <div class="text-sm text-slate-500">Получаем дерево подзадач и записи времени.</div>
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
                @create="handleCreateEntry($event)"
            />
        </section>
    </div>

    <B24Modal :open="!!editingItem" @update:open="(v) => { if (!v) editingItem = null }">
        <template #header>
            <div>
                <div class="text-sm font-semibold text-slate-900">
                    {{ isCreatingEntry ? 'Отражение часов' : 'Редактирование записи' }}
                </div>
                <div class="mt-1 text-xs text-slate-500">
                    {{ isCreatingEntry
                        ? `Часы будут списаны на задачу ID ${editingItem?.taskId}.`
                        : 'Измените сотрудника, часы, дату и описание.' }}
                </div>
            </div>
        </template>
        <template #body>
            <div v-if="editingItem" class="space-y-4">
                <B24FormField label="Сотрудник">
                    <B24Select v-model="editingItem.employeeId" :items="employeeSelectItems" class="w-full" />
                </B24FormField>
                <div class="grid gap-4 md:grid-cols-2">
                    <B24FormField label="Часы">
                        <B24InputNumber v-model="editingItem.hours" :step="0.5" class="w-full" />
                    </B24FormField>
                    <B24FormField label="Учитывать в аналитике">
                        <B24Switch v-model="editingItem.isConsidered" />
                    </B24FormField>
                </div>
                <B24FormField label="Дата">
                    <UiDatePickerInput v-model="editingItem.date" placeholder="Выберите дату" />
                </B24FormField>
                <B24FormField label="Описание">
                    <B24Textarea v-model="editingItem.description" :rows="4" class="w-full" />
                </B24FormField>
            </div>
        </template>
        <template #footer>
            <B24Button label="Отмена" color="link" @click="editingItem = null" />
            <B24Button
                :label="isCreatingEntry ? 'Отразить' : 'Сохранить'"
                color="success"
                loading-auto
                @click="editingItem && handleSaveItem(editingItem)"
            />
        </template>
    </B24Modal>

    <B24Modal :open="isReportModalOpen" @update:open="(v) => { if (!v) isReportModalOpen = false }">
        <template #header>
            <div>
                <div class="text-base font-semibold text-slate-900">Отправить часы в отчет Bitrix24?</div>
                <div class="mt-1 text-xs text-slate-500">Все учтенные часы будут добавлены в задачи Bitrix24 как отработанное время.</div>
            </div>
        </template>
        <template #body>
            <div class="flex flex-col items-center gap-3 py-4 text-center">
                <div class="inline-flex rounded-2xl bg-blue-100 p-3 text-[#0075ff]">
                    <span class="material-symbols-outlined text-3xl">cloud_upload</span>
                </div>
                <p class="text-sm leading-6 text-slate-500">
                    Записи с флагом «Учитывать в аналитике» будут добавлены как отработанное время в задачи Bitrix24.
                </p>
            </div>
        </template>
        <template #footer>
            <B24Button label="Отмена" color="link" @click="isReportModalOpen = false" />
            <B24Button
                :label="isReporting ? 'Отправка...' : 'Подтвердить'"
                color="success"
                :loading="isReporting"
                :disabled="isReporting"
                @click="handleTransferToReport"
            />
        </template>
    </B24Modal>

</div>
</template>

