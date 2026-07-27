<script setup lang="ts">
import type { B24Frame } from '@bitrix24/b24jssdk'
import { ref, onMounted, computed } from 'vue'
import type { ProjectBoardCardRecord } from '~/types/project-board'

const { initApp, processErrorGlobal } = useAppInit('ProjectReport')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()

let $b24: null | B24Frame = null
const fieldConfigStore = useFieldConfigStore()
const apiStore = useApiStore()
const toast = useToast()

// --- STATE ---
const isLoading = ref(true)
const error = ref<string | null>(null)
const items = ref<Array<Record<string, unknown>>>([])
const users = ref<Record<string, string>>({})
const currentGroupId = ref<string | null>(null)
const currentUserId = ref<string | null>(null)

const isModalOpen = ref(false)
const modalError = ref<string | null>(null)
const isSaving = ref(false)
const projectCardCache = new Map<string, ProjectBoardCardRecord>()
const lastSyncedAt = ref<string | null>(null)
const isRefreshing = ref(false)

useHead({
  title: 'Отчет по проекту'
})

const formData = ref({
    hours: '',
    description: '',
    date: new Date().toISOString().split('T')[0],
    isConsidered: true,
    employeeId: ''
})

// Dynamic field accessors (from config store)
const FIELDS = computed(() => fieldConfigStore.fields)
const entityTypeId = computed(() => fieldConfigStore.entityTypeId)

// --- LIFECYCLE ---
onMounted(async () => {
    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)

        // Load config
        await fieldConfigStore.loadFromB24($b24!)
        if (!fieldConfigStore.isConfigured) {
            error.value = fieldConfigStore.loadError || 'Конфигурация не найдена. Зайдите в Настройки → Настройка полей.'
            isLoading.value = false
            return
        }

        // Get placement context (Group ID)
        type PlacementOptions = { GROUP_ID?: string, groupId?: string, [key: string]: unknown }
        type PlacementHost = { placement?: { options?: PlacementOptions, info?: { options?: PlacementOptions } } }
        type BX24Host = { BX24?: { placement: { info: () => { options?: PlacementOptions } | undefined } } }
        const b24Host = $b24 as unknown as PlacementHost
        let options: PlacementOptions | undefined = b24Host.placement?.options || (b24Host.placement?.info && b24Host.placement.info.options)

        const windowHost = window as unknown as BX24Host
        if (!options && typeof windowHost.BX24 !== 'undefined') {
            try {
                const rawInfo = windowHost.BX24.placement.info()
                if (rawInfo) options = rawInfo.options
            } catch(e) { console.warn('BX24.placement.info failed', e) }
        }

        const groupId = options?.GROUP_ID || options?.groupId
        if (!groupId) {
            error.value = "Запустите приложение из группы Bitrix24"
            isLoading.value = false
            return
        }
        currentGroupId.value = groupId

        await loadUser()
        void loadSyncStatus()
        await fetchData()

    } catch (e: unknown) {
        processErrorGlobal(e)
        error.value = (e as Error).message
        isLoading.value = false
    }
})

// --- METHODS ---
async function loadUser() {
    try {
        const result = await $b24!.callMethod('user.current', {})
        const res = result.getData()?.result
        if (res) {
            currentUserId.value = res.ID
            formData.value.employeeId = res.ID
        }
    } catch (e) {
        console.error("User load error", e)
    }
}

async function fetchData() {
    isLoading.value = true
    error.value = null
    items.value = []

    const F = FIELDS.value

    try {
        // 1. Fetch Items filtered by PROJECT_ID
        const result = await $b24!.callMethod('crm.item.list', {
            entityTypeId: entityTypeId.value,
            filter: { ['=' + F.PROJECT_ID]: currentGroupId.value },
            select: [
                'id', 'title', 'createdTime',
                F.HOURS, F.IS_CONSIDERED,
                F.EMPLOYEE, F.DESCRIPTION,
                F.PROJECT_TITLE, F.TASK_NAME,
                F.DATE
            ],
            order: F.DATE ? { [F.DATE]: 'DESC' } : { 'id': 'DESC' }
        })
        
        const rawItems = result.getData()?.result?.items || []
        items.value = rawItems

        // 2. Fetch Users
        const userIds = [...new Set(rawItems.map((i: Record<string, unknown>) => i[F.EMPLOYEE]).filter((id: unknown) => id))]
        if (userIds.length > 0) {
            const batchCalls: Record<string, { method: string, params: Record<string, unknown> }> = {}
            userIds.forEach((id: unknown) => {
                batchCalls[`user_${id}`] = { method: 'user.get', params: { ID: id } }
            })
            const userResults = await $b24!.callBatch(batchCalls)
            const userData = userResults.getData()
            const usersData: Record<string, string> = {}
            userIds.forEach((id: unknown) => {
                const res = userData[`user_${id}`]
                if (res && !res.error && res.data && res.data[0]) {
                    const u = res.data[0]
                    usersData[String(id)] = `${u.NAME} ${u.LAST_NAME}`.trim()
                }
            })
            users.value = usersData
        }

    } catch (e: unknown) {
        error.value = "Ошибка загрузки данных: " + (e as Error).message
    } finally {
        isLoading.value = false
    }
}

async function loadSyncStatus() {
    try {
        lastSyncedAt.value = (await apiStore.getTimesheetSyncStatus()).last_synced_at
    } catch {
        // индикатор не критичен для работы страницы
    }
}

async function refreshTimesheets() {
    if (isRefreshing.value) return
    isRefreshing.value = true
    try {
        const to = new Date()
        const from = new Date()
        from.setDate(from.getDate() - 30)
        const iso = (d: Date) => d.toISOString().slice(0, 10)
        // scoped-синк за 30 дней → быстрый путь + гейт свежести (Task 2). Бэкенд всегда
        // кладёт last_synced_at в ответ — отдельный GET getTimesheetSyncStatus не нужен.
        const result = await apiStore.syncTimesheets(iso(from), iso(to))
        if (result.last_synced_at) {
            lastSyncedAt.value = result.last_synced_at
        }
        await fetchData()
    } catch (e: unknown) {
        toast.add({ title: 'Ошибка обновления данных: ' + (e as { message?: string }).message, color: 'air-primary-alert' })
    } finally {
        isRefreshing.value = false
    }
}

const openModal = () => {
    isModalOpen.value = true
    formData.value = {
        hours: '',
        description: 'Встреча',
        date: new Date().toISOString().split('T')[0],
        isConsidered: true,
        employeeId: currentUserId.value || ''
    }
    modalError.value = null
}

const closeModal = () => {
    isModalOpen.value = false
}

function resolveInnFieldCode(kind: 'OUR_INN' | 'CLIENT_INN'): string {
    return String(
        fieldConfigStore.spaFields?.[kind]
        || fieldConfigStore.fields?.[kind]
        || ''
    ).trim()
}

function extractCreatedItemId(
    rawData: { result?: string | number | { id?: unknown, itemId?: unknown, item?: { id?: unknown, ID?: unknown } } | null } | null | undefined
): string | null {
    const result = rawData?.result
    if (!result) {
        return null
    }

    if (typeof result === 'string' || typeof result === 'number') {
        const normalized = String(result).trim()
        return normalized || null
    }

    if (typeof result === 'object') {
        const directId = String(result.id || result.itemId || '').trim()
        if (directId) {
            return directId
        }

        const nestedItemId = String(result.item?.id || result.item?.ID || '').trim()
        if (nestedItemId) {
            return nestedItemId
        }
    }

    return null
}

async function getCurrentProjectCard() {
    const normalizedGroupId = String(currentGroupId.value || '').trim()
    if (!normalizedGroupId) {
        return null
    }

    if (projectCardCache.has(normalizedGroupId)) {
        return projectCardCache.get(normalizedGroupId)
    }

    try {
        const card = await apiStore.getProjectBoardCard(normalizedGroupId)
        if (card) {
            projectCardCache.set(normalizedGroupId, card)
            console.info('[ProjectReport][INN] Project card loaded', {
                groupId: normalizedGroupId,
                projectItemId: card.project_item_id,
                companyId: card.company_id,
                companyInn: card.company_inn,
                legalEntityId: card.our_legal_entity_id,
                legalEntityInn: card.our_legal_entity_inn,
            })
        } else {
            console.warn('[ProjectReport][INN] Project card is empty', { groupId: normalizedGroupId })
        }
        return card
    } catch (error) {
        console.warn('[ProjectReport] Failed to load project card for mycompany binding:', normalizedGroupId, error)
        return null
    }
}

const handleSaveMeeting = async () => {
    modalError.value = null
    if (!formData.value.hours || parseFloat(formData.value.hours) <= 0) {
        modalError.value = "Введите корректное время"
        return
    }
    if (!formData.value.description) {
        modalError.value = "Введите описание"
        return
    }

    isSaving.value = true
    const F = FIELDS.value

    try {
        // Get group name
        let groupName = ''
        if (currentGroupId.value) {
            const gRes = await $b24!.callMethod('sonet_group.get', { ID: currentGroupId.value })
            const gData = gRes.getData()?.result
            if (Array.isArray(gData) && gData[0]) groupName = gData[0].NAME
            else if (gData && gData.NAME) groupName = gData.NAME
        }

        const projectCard = await getCurrentProjectCard()
        const myCompanyId = String(projectCard?.our_legal_entity_id || '').trim()
        const projectOurInn = String(projectCard?.our_legal_entity_inn || '').trim()
        const projectClientInn = String(projectCard?.company_inn || '').trim()
        const taskNameFieldCode = String(F.TASK_NAME || '').trim()
        const ourInnFieldCode = resolveInnFieldCode('OUR_INN')
        const clientInnFieldCode = resolveInnFieldCode('CLIENT_INN')

        if (!ourInnFieldCode || !clientInnFieldCode) {
            console.warn('[ProjectReport][INN] Missing INN field mapping', {
                ourInnFieldCode,
                clientInnFieldCode,
                spaFields: fieldConfigStore.spaFields,
                fields: fieldConfigStore.fields,
            })
        }
        if (!taskNameFieldCode) {
            console.warn('[ProjectReport][TASK_NAME] Missing TASK_NAME field mapping', {
                fields: fieldConfigStore.fields,
            })
        }

        const fields: Record<string, unknown> = {
            title: formData.value.description.substring(0, 255),
            [F.HOURS]: parseFloat(formData.value.hours),
            [F.IS_CONSIDERED]: formData.value.isConsidered ? 'Y' : 'N',
            [F.EMPLOYEE]: formData.value.employeeId,
            assignedById: formData.value.employeeId,
            [F.DESCRIPTION]: formData.value.description,
            createdTime: formData.value.date + 'T00:00:00',
            [F.PROJECT_ID]: currentGroupId.value,
            [F.PROJECT_TITLE]: groupName,
            [F.DATE]: formData.value.date + 'T00:00:00'
        }

        if (F.TASK_NAME) {
            fields[F.TASK_NAME] = 'Встреча/Без задачи'
        }

        if (myCompanyId) {
            fields.mycompanyId = /^\d+$/.test(myCompanyId) ? Number(myCompanyId) : myCompanyId
        }
        if (ourInnFieldCode && projectOurInn) {
            fields[ourInnFieldCode] = projectOurInn
        }
        if (clientInnFieldCode && projectClientInn) {
            fields[clientInnFieldCode] = projectClientInn
        }

        console.info('[ProjectReport][INN] Save payload summary', {
            groupId: currentGroupId.value,
            taskNameFieldCode,
            payloadTaskName: taskNameFieldCode ? fields[taskNameFieldCode] : undefined,
            ourInnFieldCode,
            clientInnFieldCode,
            payloadOurInn: ourInnFieldCode ? fields[ourInnFieldCode] : undefined,
            payloadClientInn: clientInnFieldCode ? fields[clientInnFieldCode] : undefined,
            payloadMycompanyId: fields.mycompanyId,
        })

        const createRes = await $b24!.callMethod('crm.item.add', {
            entityTypeId: entityTypeId.value,
            fields
        })
        const createdItemId = extractCreatedItemId(createRes?.getData?.())
        console.info('[ProjectReport][INN] Create result', {
            createdItemId,
            rawResult: createRes?.getData?.()?.result,
        })

        if (createdItemId && (ourInnFieldCode || clientInnFieldCode)) {
            try {
                const verifyRes = await $b24!.callMethod('crm.item.get', {
                    entityTypeId: entityTypeId.value,
                    id: createdItemId,
                })
                const verifyItem = verifyRes?.getData?.()?.result?.item || verifyRes?.getData?.()?.item || {}
                console.info('[ProjectReport][INN] Verify saved item', {
                    createdItemId,
                    taskNameFieldCode,
                    savedTaskName: taskNameFieldCode ? verifyItem?.[taskNameFieldCode] : undefined,
                    ourInnFieldCode,
                    clientInnFieldCode,
                    savedOurInn: ourInnFieldCode ? verifyItem?.[ourInnFieldCode] : undefined,
                    savedClientInn: clientInnFieldCode ? verifyItem?.[clientInnFieldCode] : undefined,
                    savedMycompanyId: verifyItem?.mycompanyId,
                })
            } catch (verifyError) {
                console.warn('[ProjectReport][INN] Failed to verify created item', {
                    createdItemId,
                    error: verifyError,
                })
            }
        }

        closeModal()
        await fetchData()

        // Фаза 1 sync-offload: полный синк таймшитов на критпути сохранения карточки убран
        // (тот же антипаттерн, что и в embedded.vue). Кеш карточки просто сбрасывается —
        // актуализация придёт следующим фоновым синком/планировщиком или кнопкой «Обновить»
        // (write-through при сохранении — Фаза 3).
        projectCardCache.clear()
    } catch (e: unknown) {
        modalError.value = (e as Error).message
    } finally {
        isSaving.value = false
    }
}
</script>

<template>
    <div class="h-screen flex flex-col bg-slate-50 font-sans text-slate-800">
        <!-- Header -->
        <header class="bg-white border-b px-6 py-4 flex items-center justify-between shrink-0 shadow-sm z-10">
            <div>
                <h1 class="text-xl font-bold flex items-center gap-2 text-slate-800">
                    <span class="material-symbols-outlined text-purple-600">topic</span>
                    Отчет по проекту
                </h1>
                <p v-if="currentGroupId" class="text-xs text-slate-500 mt-1">ID Проекта: {{ currentGroupId }}</p>
            </div>
            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 text-xs text-slate-500">
                    <span v-if="lastSyncedAt">данные на {{ new Date(lastSyncedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }}</span>
                    <button :disabled="isRefreshing" class="px-2 py-1 border rounded hover:bg-slate-50 disabled:opacity-50" @click="refreshTimesheets">
                        {{ isRefreshing ? 'Обновляю…' : 'Обновить' }}
                    </button>
                </div>
                <button class="p-2 text-slate-500 hover:text-blue-600 transition-colors rounded-full hover:bg-blue-50" @click="fetchData">
                    <span class="material-symbols-outlined">refresh</span>
                </button>
            </div>
        </header>

        <!-- Content -->
        <main class="flex-1 overflow-auto p-6">
            <div v-if="isLoading" class="flex justify-center items-center h-64">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"/>
            </div>
            
            <div v-else-if="error" class="bg-red-50 text-red-600 p-4 rounded-lg flex items-center gap-3 border border-red-100 shadow-sm">
                <span class="material-symbols-outlined">error</span>
                {{ error }}
            </div>
            
            <div v-else>
                 <div class="flex justify-between items-center mb-6">
                    <div class="flex gap-4">
                        <div class="bg-white px-4 py-3 rounded-xl shadow-sm border border-slate-100">
                            <div class="text-xs text-slate-400 uppercase tracking-wider font-medium mb-1">Всего часов</div>
                            <div class="text-2xl font-bold text-slate-700">
                                {{ items.reduce((sum, i) => sum + (parseFloat(i[FIELDS.HOURS]) || 0), 0).toFixed(2) }}
                            </div>
                        </div>
                    </div>
                    <button class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium flex items-center gap-2 shadow-sm transition-all active:transform active:scale-95" @click="openModal">
                        <span class="material-symbols-outlined text-[20px]">add_circle</span>
                        Списать на встречи
                    </button>
                </div>

                <div class="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200">
                    <table class="w-full text-sm text-left">
                        <thead class="bg-slate-50 text-slate-500 uppercase text-xs font-semibold border-b border-slate-200">
                            <tr>
                                <th class="px-6 py-4">Дата</th>
                                <th class="px-6 py-4">Сотрудник</th>
                                <th class="px-6 py-4">Задача / Описание</th>
                                <th class="px-6 py-4 text-right">Часы</th>
                                <th class="px-6 py-4 text-center">Учет</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            <tr v-for="item in items" :key="item.id" class="hover:bg-slate-50 transition-colors">
                                <td class="px-6 py-4 whitespace-nowrap text-slate-600">
                                    {{ item[FIELDS.DATE] ? new Date(item[FIELDS.DATE]).toLocaleDateString() : (item.createdTime ? new Date(item.createdTime).toLocaleDateString() : '-') }}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap font-medium text-slate-700">
                                    <div class="flex items-center gap-2">
                                        <div class="w-6 h-6 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center text-[10px] font-bold">
                                            {{ (users[item[FIELDS.EMPLOYEE]] || '?')[0] }}
                                        </div>
                                        {{ users[item[FIELDS.EMPLOYEE]] || 'Неизвестный' }}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                     <div class="font-medium text-slate-800">{{ item[FIELDS.TASK_NAME] || 'Без задачи' }}</div>
                                     <div class="text-xs text-slate-500 mt-1 line-clamp-1">{{ item.title }}</div>
                                </td>
                                <td class="px-6 py-4 text-right font-bold text-slate-700">
                                    {{ parseFloat(item[FIELDS.HOURS] || 0).toFixed(2) }}
                                </td>
                                <td class="px-6 py-4 text-center">
                                     <span 
                                        :class="(item[FIELDS.IS_CONSIDERED] === 'Y' || item[FIELDS.IS_CONSIDERED] === true) ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'"
                                        class="px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider"
                                     >
                                        {{ (item[FIELDS.IS_CONSIDERED] === 'Y' || item[FIELDS.IS_CONSIDERED] === true) ? 'Да' : 'Нет' }}
                                     </span>
                                </td>
                            </tr>
                            <tr v-if="items.length === 0">
                                <td colspan="5" class="px-6 py-12 text-center text-slate-400">
                                    Нет записей для этого проекта
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </main>

        <!-- Modal -->
        <div v-if="isModalOpen" class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-white w-3/5 min-w-[600px] rounded-2xl shadow-xl overflow-hidden transform transition-all scale-100 border border-slate-100">
                 <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                    <h3 class="font-bold text-lg text-slate-800">Списание на встречи</h3>
                    <button class="text-slate-400 hover:text-slate-600 transition-colors" @click="closeModal">
                        <span class="material-symbols-outlined">close</span>
                    </button>
                </div>
                
                <div class="p-6 space-y-4">
                     <div v-if="modalError" class="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4 border border-red-100">
                        {{ modalError }}
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Дата</label>
                        <input v-model="formData.date" type="date" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700">
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Часы</label>
                        <input v-model="formData.hours" type="number" step="0.5" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-medium text-slate-700" placeholder="0.0">
                    </div>
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Описание</label>
                        <textarea v-model="formData.description" class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-slate-700 h-24 resize-none" placeholder="Детали встречи..."/>
                    </div>

                     <div class="flex items-center gap-2">
                         <input id="modalIsConsidered" v-model="formData.isConsidered" type="checkbox" class="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500">
                         <label for="modalIsConsidered" class="text-sm text-slate-700 font-medium">Учитывать часы (Billable)</label>
                     </div>
                </div>

                <div class="p-6 border-t bg-slate-50 flex gap-3">
                    <button class="flex-1 bg-white text-slate-700 border border-slate-300 font-medium py-2.5 rounded-lg hover:bg-slate-50 transition-colors" @click="closeModal">
                        Отмена
                    </button>
                    <button :disabled="isSaving" class="flex-1 bg-blue-600 text-white font-medium py-2.5 rounded-lg shadow-sm hover:bg-blue-700 active:transform active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed" @click="handleSaveMeeting">
                        {{ isSaving ? 'Сохранение...' : 'Сохранить' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>
