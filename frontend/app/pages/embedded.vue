<script setup lang="ts">
/**
 * Вкладка задачи (placement TASK_VIEW_TAB) — рабочий экран учёта часов.
 *
 * Редизайн «вариант A — родной портал», сентябрь 2026. Что изменилось и почему:
 *
 *  1. ОДНА КОЛОНКА. Было: сетка `1fr 380px` без брейкпоинтов. Вкладка живёт в
 *     iframe карточки задачи, ширину которого задаёт портал: на 640 px дереву
 *     оставалось ~230 px, на 400 px вёрстка ломалась. Стало: одна колонка на
 *     любой ширине, плотность перестраивается на 660 и 480 px
 *     (`utils/taskTabLayout.ts`).
 *
 *  2. ФОРМА СПИСАНИЯ РАСКРЫВАЕТСЯ В СПИСКЕ. Модальное окно во фрейме с
 *     автовысотой (`BX24.fitWindow`) центрируется по всему фрейму: при длинном
 *     дереве оно оказывается вне видимой части страницы. Инлайн-форма
 *     появляется там, куда нажали, и этой проблемы не имеет вовсе.
 *
 *  3. ДЕЙСТВИЯ У ЗАПИСИ ВИДНЫ ВСЕГДА — раньше проявлялись по наведению, то есть
 *     на тачскрине не существовали.
 *
 *  4. СУММ НЕТ. Поле «Стоимость часа» и «Сумма для клиента» убраны: их видят
 *     руководители в отчётах. На сохранение это не влияет — снимок ставки
 *     пишется из карточки проекта (`applyProjectContextFields`), а поле на
 *     экране было к тому же нерабочим: `clientHourRate` — computed без сеттера,
 *     и ввод в него Vue молча отбрасывал.
 *
 *  5. Лаймовые остатки бренда заменены на токены Air, контраст акцентной
 *     кнопки доведён до AA (см. `utils/colorContrast.ts` и его тест).
 *
 *  6. «В отчёт Битрикс24» и «Excel» переехали сюда из `pages/task.vue` —
 *     экрана, на который в проде ничего не вело. В макете они закреплены у
 *     нижнего края; здесь это блок в конце вкладки, а на длинном дереве та же
 *     пара дублируется в строке инструментов наверху — почему именно так,
 *     разобрано в `utils/taskTabLayout.ts` → `shouldMirrorFooterActions`.
 *
 *  7. СТРОКА ИНСТРУМЕНТОВ из макета: «Все записи / Мои» и кнопка периода.
 *     Переключатель — не новое состояние, а тот же фильтр по сотруднику,
 *     выставленный на себя; выбор конкретного человека остался в
 *     раскрывающейся панели фильтра, где он и нужен руководителю.
 *
 * Сборка полей списания идёт через `useTimesheetEntry` — тот же путь, что
 * раньше был скопирован в этот файл построчно. Копия удалена: решения о том,
 * что писать в запись и что блокирует сохранение, живут в
 * `utils/timesheetEntry.ts` и покрыты тестами.
 */
import type { B24Frame } from '@bitrix24/b24jssdk'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import HelpSidePanel from '@/components/HelpSidePanel.vue'
import TaskExportBar from '@/components/task/TaskExportBar.vue'
import TaskTabCard from '@/components/task/TaskTabCard.vue'
import { canOpenNativeApplication, resolveTaskPlacementId, useIframeResizeOnToggle } from '@/composables/useTaskPlacement'
import { useTaskTreeLoader } from '@/composables/useTaskTreeLoader'
import { useTimesheetEntry } from '@/composables/useTimesheetEntry'
import { filterTaskTree, findTaskIdForItem } from '@/utils/taskTree'
import { requestIframeAutoHeight, requestIframeFullHeight } from '@/utils/iframe-resizer'
import { resolveTaskTabLayout, shouldMirrorFooterActions, taskTabLayoutClass } from '@/utils/taskTabLayout'
import { countVisibleRows, formatPeriodLabel, formatTreeSummaryLine, summarizeTaskTree } from '@/utils/taskTabFormat'
import { CSV_BOM, buildCsvFileName, buildElapsedItemBatch, buildTaskTreeCsv } from '@/utils/taskTabExport'
import { draftFromItem, makeTaskEntryDraft, type TaskEntryDraft, type TaskFormAnchor } from '@/utils/taskTabEntry'
import type { TaskWorkspaceItem } from '~/types/task-workspace'

const { initApp, processErrorGlobal } = useAppInit('EmbeddedPage')
const { $initializeB24Frame } = useNuxtApp()
const { locales: localesI18n, setLocale } = useI18n()
const toast = useToast()

let $b24: null | B24Frame = null
const apiStore = useApiStore()
const { prepareEntryFields } = useTimesheetEntry()

const {
    isLoading,
    error,
    usersList,
    currentUserId,
    taskTree,
    config,
    loadConfigAndUsers,
    loadTaskTree
} = useTaskTreeLoader()

// --- СОСТОЯНИЕ ЭКРАНА ---
const rootTaskId = ref<string | null>(null)
const expandedTasks = ref<Set<string>>(new Set())
const anchor = ref<TaskFormAnchor | null>(null)
const draft = ref<TaskEntryDraft | null>(null)
const isSaving = ref(false)
const notice = ref<string | null>(null)

const isHelpOpen = ref(false)
const isNativeSidePanelAvailable = ref(false)
const isFilterOpen = ref(false)
/**
 * Где раскрыто подтверждение переноса: у верхнего дубля кнопок или у нижнего
 * блока. Не булево, потому что кнопок две пары — подтверждение должно
 * появляться там, куда нажали, иначе на длинном дереве оно оказывается за
 * нижним краем экрана.
 */
const reportConfirmAt = ref<'top' | 'bottom' | null>(null)
const isReporting = ref(false)

const filterEmployeeId = ref<string>('')
const filterDateFrom = ref<string>('')
const filterDateTo = ref<string>('')

// --- РАСКЛАДКА ПО ШИРИНЕ ФРЕЙМА ---
const frameWidth = ref(0)
const layout = computed(() => resolveTaskTabLayout(frameWidth.value))
const layoutClass = computed(() => taskTabLayoutClass(layout.value.mode))

function measureFrameWidth() {
    frameWidth.value = window.innerWidth
}

// --- ВЫЧИСЛЯЕМОЕ ---
const isFilterActive = computed(() =>
    !!filterEmployeeId.value || !!filterDateFrom.value || !!filterDateTo.value
)

const filteredTaskTree = computed(() => filterTaskTree(taskTree.value, {
    employeeId: filterEmployeeId.value,
    dateFrom: filterDateFrom.value,
    dateTo: filterDateTo.value
}))

const treeSummary = computed(() => summarizeTaskTree(filteredTaskTree.value))
const summaryLine = computed(() => formatTreeSummaryLine(treeSummary.value))
const hasTree = computed(() => filteredTaskTree.value.length > 0)

// --- СТРОКА ИНСТРУМЕНТОВ ---
/**
 * «Все записи / Мои» — тот же переключатель, что в макете. Он не заводит
 * второго состояния: «Мои» — это ровно фильтр по сотруднику, выставленный на
 * себя, поэтому выбор другого человека в панели фильтра просто снимает
 * подсветку с обеих кнопок, и рассинхрона между ними и фильтром не бывает.
 */
const isMineOnly = computed(() =>
    !!currentUserId.value && String(filterEmployeeId.value) === String(currentUserId.value)
)

const periodLabel = computed(() => formatPeriodLabel(filterDateFrom.value, filterDateTo.value))

/** На длинном дереве выгрузки дублируются наверх — см. shouldMirrorFooterActions. */
const showTopExports = computed(() =>
    hasTree.value && shouldMirrorFooterActions(countVisibleRows(filteredTaskTree.value, expandedTasks.value))
)

// --- ИНИЦИАЛИЗАЦИЯ ---
onMounted(async () => {
    measureFrameWidth()
    window.addEventListener('resize', measureFrameWidth)

    if (typeof (window as unknown as Record<string, unknown>).BX24 !== 'undefined' && canOpenNativeApplication()) {
        isNativeSidePanelAvailable.value = true
    }

    try {
        $b24 = await $initializeB24Frame()
        await initApp($b24, localesI18n, setLocale)

        const tid = resolveTaskPlacementId($b24)
        if (!tid) {
            error.value = 'Не передан ID задачи. Откройте приложение во вкладке задачи.'
            isLoading.value = false
            return
        }
        rootTaskId.value = tid

        await loadConfigAndUsers($b24, { includeProfile: true })
        if (config.value?.DEFAULT_SMART_PROCESS_ID) {
            await reloadWorkspace()
        }
    } catch (e: unknown) {
        processErrorGlobal(e)
        error.value = (e as { message?: string }).message || String(e)
    } finally {
        // Единственный владелец завершения загрузки: какой бы веткой ни закончился
        // init (нет ID задачи, конфигурация не загрузилась, отказ REST), спиннер гаснет.
        isLoading.value = false
    }
})

onBeforeUnmount(() => {
    window.removeEventListener('resize', measureFrameWidth)
})

/**
 * Перечитывает дерево задачи.
 *
 * Раскрытые задачи сохраняются: после сохранения записи человек должен видеть
 * то же место дерева, где работал, а не свёрнутый корень. Синк с Битриксом на
 * открытии не делается — данные читаются из БД, свежесть держит фоновый
 * планировщик и кнопка «Обновить» (фаза 1 sync-offload).
 */
async function reloadWorkspace() {
    if (!$b24 || !rootTaskId.value) {
        return
    }

    const previouslyExpanded = new Set(expandedTasks.value)
    await loadTaskTree($b24, rootTaskId.value)
    previouslyExpanded.add(rootTaskId.value)
    expandedTasks.value = previouslyExpanded
}

// --- АВТОВЫСОТА ФРЕЙМА ---
/*
 * Высоту фрейма пересчитываем после каждой перерисовки, меняющей высоту
 * содержимого: раскрытие задачи, открытие формы, смена набора записей,
 * раскрытие фильтра. Без этого форма раскрывается внутри фрейма прежней
 * высоты и нижняя её часть оказывается за обрезкой.
 */
watch(
    () => [
        isLoading.value,
        filteredTaskTree.value,
        expandedTasks.value.size,
        anchor.value,
        isFilterOpen.value,
        reportConfirmAt.value,
        showTopExports.value,
        notice.value,
        layout.value.mode
    ],
    async () => {
        await nextTick()
        requestIframeAutoHeight()
    },
    { deep: false }
)

useIframeResizeOnToggle(isHelpOpen)

function openHelp() {
    if (isNativeSidePanelAvailable.value) {
        try {
            // Нативный слайдер выносит справочник за пределы фрейма — там ему
            // не мешает ни ширина вкладки, ни её автовысота.
            // @ts-expect-error BX24 инжектится порталом и не типизирован
            window.BX24.openApplication({ url: '/guide?from=slider' }, { title: 'Справочник', width: 900 })
            return
        } catch (e) {
            console.error('Native slider failed, using fallback', e)
        }
    }

    requestIframeFullHeight()
    isHelpOpen.value = true
}

// --- ДЕРЕВО ---
function toggleTask(taskId: string) {
    if (expandedTasks.value.has(taskId)) {
        expandedTasks.value.delete(taskId)
    } else {
        expandedTasks.value.add(taskId)
    }
}

function resetFilter() {
    filterEmployeeId.value = ''
    filterDateFrom.value = ''
    filterDateTo.value = ''
}

function showAllEmployees() {
    filterEmployeeId.value = ''
}

function showMineOnly() {
    filterEmployeeId.value = String(currentUserId.value || '')
}

// --- ФОРМА ---
function openCreateForm(taskId: string) {
    const targetTaskId = String(taskId || rootTaskId.value || '')
    if (!targetTaskId) {
        notice.value = 'Не удалось определить задачу для списания.'
        return
    }

    notice.value = null
    // Форма создания раскрывается под шапкой задачи, поэтому задача обязана
    // быть раскрыта — иначе человек нажал «+» и ничего не увидел.
    expandedTasks.value.add(targetTaskId)
    draft.value = makeTaskEntryDraft({
        taskId: targetTaskId,
        employeeId: currentUserId.value || usersList.value[0]?.ID || '',
        today: new Date()
    })
    anchor.value = { kind: 'create', taskId: targetTaskId }
}

function openEditForm(item: TaskWorkspaceItem, taskId: string) {
    notice.value = null
    const ownerTaskId = findTaskIdForItem(item.id, taskTree.value) || taskId || rootTaskId.value || ''
    draft.value = draftFromItem(item, String(ownerTaskId))
    anchor.value = { kind: 'edit', taskId: String(ownerTaskId), itemId: String(item.id) }
}

function closeForm() {
    anchor.value = null
    draft.value = null
}

/** Создание и правка идут одним путём: отличие только в наличии id. */
async function saveDraft(payload: TaskEntryDraft) {
    if (!config.value || !$b24) {
        return
    }

    isSaving.value = true
    notice.value = null

    try {
        const taskId = String(payload.taskId || rootTaskId.value || '')
        const { fields, validation } = await prepareEntryFields($b24, config.value, { ...payload, taskId }, taskTree.value)

        if (validation.warning) {
            console.warn('[Embedded]', validation.warning)
        }

        if (validation.error) {
            notice.value = validation.error
            toast.add({ title: validation.error, color: 'air-primary-alert' })
            return
        }

        // Через бэкенд, а не напрямую в Битрикс: только так на списание можно
        // наложить серверное правило (закрытие месяца).
        if (payload.id) {
            await apiStore.updateTimesheetEntry(payload.id, fields)
        } else {
            await apiStore.createTimesheetEntry(fields)
        }

        closeForm()
        await reloadWorkspace()
        toast.add({ title: payload.id ? 'Запись сохранена' : 'Часы списаны', color: 'air-primary-success' })
    } catch (e: unknown) {
        const message = 'Ошибка сохранения: ' + ((e as { message?: string }).message || String(e))
        notice.value = message
        toast.add({ title: message, color: 'air-primary-alert' })
    } finally {
        isSaving.value = false
    }
}

/**
 * Разделение записи — две операции: у исходной уменьшаются часы, отделённая
 * часть создаётся отдельной записью. Обе идут через бэкенд: иначе половина
 * операции обошла бы серверную проверку закрытого периода.
 */
async function splitDraft(payload: TaskEntryDraft) {
    if (!config.value || !$b24 || !payload.id) {
        return
    }

    isSaving.value = true
    notice.value = null

    try {
        const splitHours = Number(payload.splitHours)
        const splitTaskId = findTaskIdForItem(payload.id, taskTree.value)
        if (!splitTaskId) {
            notice.value = 'Не удалось определить задачу для разделяемой записи.'
            return
        }

        const splitDescription = `${payload.description} (разделено)`.trim()
        const { fields, validation } = await prepareEntryFields(
            $b24,
            config.value,
            {
                ...payload,
                id: null,
                taskId: splitTaskId,
                description: splitDescription,
                hours: splitHours,
                isConsidered: payload.splitInvert ? !payload.isConsidered : payload.isConsidered
            },
            taskTree.value
        )

        if (validation.warning) {
            console.warn('[Embedded]', validation.warning)
        }

        if (validation.error) {
            notice.value = validation.error
            toast.add({ title: validation.error, color: 'air-primary-alert' })
            return
        }

        await apiStore.updateTimesheetEntry(payload.id, {
            [String(config.value.FIELDS.HOURS)]: Number(payload.hours) - splitHours
        })
        await apiStore.createTimesheetEntry(fields)

        closeForm()
        await reloadWorkspace()
        toast.add({ title: 'Запись разделена', color: 'air-primary-success' })
    } catch (e: unknown) {
        const message = 'Ошибка разделения: ' + ((e as { message?: string }).message || String(e))
        notice.value = message
        toast.add({ title: message, color: 'air-primary-alert' })
    } finally {
        isSaving.value = false
    }
}

/**
 * Удаление записи.
 *
 * Идёт напрямую в Битрикс: эндпоинта удаления на бэкенде нет, и заводить его
 * ради редизайна вкладки — отдельная задача с серверной проверкой периода.
 */
async function deleteItem(item: TaskWorkspaceItem) {
    if (!config.value || !$b24 || !item?.id) {
        return
    }

    const label = item.description ? `«${String(item.description).substring(0, 60)}»` : `#${item.id}`
    if (!confirm(`Удалить запись ${label}?`)) {
        return
    }

    isSaving.value = true
    notice.value = null

    try {
        await ($b24 as B24Frame).callMethod('crm.item.delete', {
            entityTypeId: config.value.DEFAULT_SMART_PROCESS_ID,
            id: item.id
        })

        if (anchor.value?.kind === 'edit' && String(anchor.value.itemId) === String(item.id)) {
            closeForm()
        }
        await reloadWorkspace()
        toast.add({ title: 'Запись удалена', color: 'air-primary-success' })
    } catch (e: unknown) {
        const message = 'Ошибка удаления: ' + ((e as { message?: string }).message || String(e))
        notice.value = message
        toast.add({ title: message, color: 'air-primary-alert' })
    } finally {
        isSaving.value = false
    }
}

/** Удаление из открытой формы правки. */
function deleteDraft(payload: TaskEntryDraft) {
    deleteItem({
        id: String(payload.id),
        hours: payload.hours,
        isConsidered: payload.isConsidered,
        description: payload.description,
        employeeId: payload.employeeId,
        employeeName: '',
        date: payload.date
    })
}

// --- ВЫГРУЗКИ ---
/**
 * CSV по дереву. Файл собирается в памяти: `data:`-ссылка на длинном дереве
 * упирается в ограничение длины URL, а Blob — нет.
 */
function exportCsv() {
    const csv = CSV_BOM + buildTaskTreeCsv(filteredTaskTree.value)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')

    link.href = url
    link.download = buildCsvFileName(rootTaskId.value)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
}

/** Перенос учтённых часов в штатный отчёт задачи Битрикс24. */
async function transferToReport() {
    const { batch, count } = buildElapsedItemBatch(filteredTaskTree.value)

    if (count === 0) {
        reportConfirmAt.value = null
        notice.value = 'Нет учтённых часов для переноса.'
        return
    }

    isReporting.value = true
    try {
        await ($b24 as B24Frame).callBatch(batch)
        toast.add({ title: `Перенесено записей: ${count}`, color: 'air-primary-success' })
    } catch (e: unknown) {
        const message = 'Ошибка переноса: ' + ((e as { message?: string }).message || String(e))
        notice.value = message
        toast.add({ title: message, color: 'air-primary-alert' })
    } finally {
        isReporting.value = false
        reportConfirmAt.value = null
    }
}
</script>

<template>
<div class="ms-page-shell task-tab" :class="layoutClass">
    <section class="task-tab__bar">
        <div class="task-tab__heading">
            <h1 class="task-tab__title">Учёт часов</h1>
            <p class="task-tab__summary">{{ summaryLine }}</p>
        </div>

        <div class="task-tab__bar-actions">
            <B24Button
                label="Списать часы"
                color="air-primary"
                size="sm"
                :disabled="isLoading || !rootTaskId"
                @click="openCreateForm(rootTaskId || '')"
            />
            <button
                type="button"
                class="task-tab__icon-btn"
                title="Справочник"
                aria-label="Справочник"
                @click="openHelp"
            >
                <span class="material-symbols-outlined text-[20px] leading-none">help</span>
            </button>
        </div>
    </section>

    <!--
        Строка инструментов из макета: переключатель «Все записи / Мои» и
        кнопка периода. Оба всегда на виду — это то, чем пользуются каждый
        день, в отличие от выбора конкретного сотрудника, который живёт в
        раскрывающейся панели фильтра.
    -->
    <section v-if="!error && !isLoading" class="task-tab__tools">
        <div class="task-tab__scope" role="group" aria-label="Чьи записи показывать">
            <button
                type="button"
                class="task-tab__scope-btn"
                :class="{ 'task-tab__scope-btn--on': !filterEmployeeId }"
                :aria-pressed="!filterEmployeeId"
                @click="showAllEmployees"
            >
                Все записи
            </button>
            <button
                type="button"
                class="task-tab__scope-btn"
                :class="{ 'task-tab__scope-btn--on': isMineOnly }"
                :aria-pressed="isMineOnly"
                :disabled="!currentUserId"
                @click="showMineOnly"
            >
                Мои
            </button>
        </div>

        <button
            type="button"
            class="task-tab__tool"
            :class="{ 'task-tab__tool--on': isFilterOpen || isFilterActive }"
            :aria-pressed="isFilterOpen"
            :aria-expanded="isFilterOpen"
            title="Период и сотрудник"
            @click="isFilterOpen = !isFilterOpen"
        >
            <span class="material-symbols-outlined text-[18px] leading-none">calendar_month</span>
            {{ periodLabel }}
        </button>

        <B24Button
            v-if="isFilterActive"
            label="Сбросить"
            color="air-tertiary-no-accent"
            size="xs"
            @click="resetFilter"
        />

        <!-- Дубль выгрузок на длинном дереве: до нижнего блока пришлось бы листать. -->
        <TaskExportBar
            v-if="showTopExports"
            class="task-tab__tools-exports"
            :confirm-open="reportConfirmAt === 'top'"
            :reporting="isReporting"
            :filter-active="isFilterActive"
            :compact="true"
            @report="reportConfirmAt = 'top'"
            @confirm="transferToReport"
            @cancel="reportConfirmAt = null"
            @export-csv="exportCsv"
        />
    </section>

    <section v-if="isFilterOpen" class="task-tab__filter" :class="{ 'task-tab__filter--stacked': layout.stackedFilters }">
        <label class="task-tab__filter-field">
            <span class="task-tab__filter-label">Сотрудник</span>
            <select v-model="filterEmployeeId">
                <option value="">Все сотрудники</option>
                <option v-for="u in usersList" :key="String(u.ID)" :value="u.ID">{{ u.NAME }} {{ u.LAST_NAME }}</option>
            </select>
        </label>
        <label class="task-tab__filter-field">
            <span class="task-tab__filter-label">Дата от</span>
            <input v-model="filterDateFrom" type="date">
        </label>
        <label class="task-tab__filter-field">
            <span class="task-tab__filter-label">Дата до</span>
            <input v-model="filterDateTo" type="date">
        </label>
    </section>

    <p v-if="notice" class="task-tab__notice" role="alert">{{ notice }}</p>

    <!-- Ошибка идёт ПЕРЕД загрузкой: иначе залипший isLoading прячет причину отказа. -->
    <section v-if="error" class="task-tab__state task-tab__state--error">
        <span class="material-symbols-outlined text-[28px]">error</span>
        <div>
            <div class="task-tab__state-title">Ошибка загрузки</div>
            <p class="task-tab__state-text">{{ error }}</p>
        </div>
    </section>

    <section v-else-if="isLoading" class="task-tab__state">
        <span class="material-symbols-outlined animate-spin text-[28px]">progress_activity</span>
        <div>
            <div class="task-tab__state-title">Загрузка данных</div>
            <p class="task-tab__state-text">Получаем задачи и записи времени.</p>
        </div>
    </section>

    <template v-else>
        <div v-if="hasTree" class="task-tab__tree">
            <TaskTabCard
                v-for="task in filteredTaskTree"
                :key="task.taskId"
                :node="task"
                :level="0"
                :layout="layout"
                :expanded-tasks="expandedTasks"
                :anchor="anchor"
                :draft="draft"
                :users="usersList"
                :busy="isSaving"
                @toggle="toggleTask"
                @create="openCreateForm"
                @edit="openEditForm"
                @remove="deleteItem"
                @save="saveDraft"
                @split="splitDraft"
                @remove-draft="deleteDraft"
                @cancel="closeForm"
            />
        </div>

        <section v-else class="task-tab__state">
            <span class="material-symbols-outlined text-[28px]">filter_alt_off</span>
            <div>
                <div class="task-tab__state-title">Записей нет</div>
                <p class="task-tab__state-text">
                    {{ isFilterActive ? 'Под фильтр ничего не попало — сбросьте его.' : 'Нажмите «Списать часы», чтобы добавить первую запись.' }}
                </p>
            </div>
        </section>

        <!--
            Панель выгрузок в конце вкладки. В макете она закреплена у нижнего
            края; здесь это обычный блок — во фрейме с автовысотой и `sticky`, и
            `fixed` считаются от области просмотра самого фрейма, которая равна
            всему содержимому, то есть прилипли бы к низу дерева, а не к низу
            экрана. Взамен на длинном дереве те же кнопки дублируются в строке
            инструментов наверху (`shouldMirrorFooterActions`).
        -->
        <section class="task-tab__footer">
            <TaskExportBar
                :confirm-open="reportConfirmAt === 'bottom'"
                :reporting="isReporting"
                :filter-active="isFilterActive"
                :compact="false"
                @report="reportConfirmAt = 'bottom'"
                @confirm="transferToReport"
                @cancel="reportConfirmAt = null"
                @export-csv="exportCsv"
            />
        </section>
    </template>

    <HelpSidePanel v-model="isHelpOpen" />
</div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

/*
 * Токены Air переопределяются в пределах вкладки — ради контраста AA.
 *
 * Штатная заливка акцентных компонентов UI Kit (--ui-color-accent-main-primary,
 * #0075ff) даёт с белым текстом 4.21:1, а с тёмным — 4.24:1: и то и другое ниже
 * нормы AA 4.5:1 для обычного текста. Берём соседний тон того же синего ряда
 * палитры, --ui-color-blue-80 (#0069e6): белый текст на нём — 5.04:1.
 * Вторичная кнопка по умолчанию красит подпись в --ui-color-base-3 (3.0:1),
 * поэтому подпись переводится на --ui-color-base-2 (6.79:1).
 * Расчёт и защита от возврата — utils/colorContrast.ts + tests/colorContrast.test.ts.
 */
.task-tab {
    --ui-color-design-filled-bg: var(--ui-color-blue-80);
    --ui-color-design-filled-stroke: var(--ui-color-blue-80);
    --ui-color-design-outline-na-content: var(--ui-color-base-2);
    --ui-color-design-outline-na-stroke: var(--ui-color-base-6);

    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
    padding: 10px;
}

.task-tab__bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.task-tab__heading {
    min-width: 0;
}

.task-tab__title {
    font-size: 16px;
    font-weight: 600;
    color: var(--ui-color-base-1);
}

/* Итоги по задаче — одной строкой, как требует вариант A. */
.task-tab__summary {
    margin-top: 2px;
    font-size: 12px;
    color: var(--ui-color-base-2);
}

.task-tab__bar-actions {
    display: flex;
    align-items: center;
    gap: 6px;
}

.task-tab__icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 8px;
    background: var(--ui-color-bg-content-primary);
    color: var(--ui-color-base-2);
    cursor: pointer;
}

.task-tab__icon-btn:hover {
    border-color: var(--ui-color-base-5);
    color: var(--ui-color-base-1);
}

.task-tab__icon-btn--on {
    border-color: var(--ui-color-accent-main-link);
    background: var(--ui-color-accent-soft-blue-2);
    color: var(--ui-color-accent-main-link);
}

/*
 * Строка инструментов — сразу под шапкой, как в макете. На узком фрейме
 * переносится по элементам, а не складывается в колонку: три коротких
 * управляющих элемента в столбик съедали бы половину первого экрана.
 */
.task-tab__tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
}

.task-tab__scope {
    display: inline-flex;
    overflow: hidden;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 8px;
    background: var(--ui-color-bg-content-primary);
}

.task-tab__scope-btn {
    min-height: 30px;
    padding: 0 10px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--ui-color-base-2);
    white-space: nowrap;
    cursor: pointer;
}

.task-tab__scope-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.task-tab__scope-btn--on {
    background: var(--ui-color-accent-soft-blue-2);
    color: var(--ui-color-accent-main-link);
}

.task-tab__tool {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 30px;
    padding: 0 10px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 8px;
    background: var(--ui-color-bg-content-primary);
    font-size: 12.5px;
    font-weight: 500;
    color: var(--ui-color-base-2);
    white-space: nowrap;
    cursor: pointer;
}

.task-tab__tool:hover {
    border-color: var(--ui-color-base-5);
    color: var(--ui-color-base-1);
}

.task-tab__tool--on {
    border-color: var(--ui-color-accent-main-link);
    background: var(--ui-color-accent-soft-blue-2);
    color: var(--ui-color-accent-main-link);
}

/* Дубль выгрузок прижимается к правому краю строки, чтобы не путаться с фильтрами. */
.task-tab__tools-exports {
    margin-left: auto;
}

.task-tab__filter {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 12px;
    background: var(--ui-color-bg-content-secondary);
}

.task-tab__filter--stacked {
    flex-direction: column;
    align-items: stretch;
}

.task-tab__filter-field {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 4px;
    min-width: 140px;
}

.task-tab__filter-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ui-color-base-2);
}

.task-tab__notice {
    padding: 10px 12px;
    border: 1px solid var(--ui-color-red-30);
    border-radius: 10px;
    background: var(--ui-color-red-15);
    font-size: 13px;
    color: var(--ui-color-red-80);
}

.task-tab__state {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 24px 16px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 12px;
    background: var(--ui-color-bg-content-primary);
    color: var(--ui-color-base-2);
}

.task-tab__state--error {
    border-color: var(--ui-color-red-30);
    background: var(--ui-color-red-15);
    color: var(--ui-color-red-80);
}

.task-tab__state-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--ui-color-base-1);
}

.task-tab__state--error .task-tab__state-title {
    color: var(--ui-color-red-80);
}

.task-tab__state-text {
    margin-top: 2px;
    font-size: 13px;
    line-height: 1.5;
}

.task-tab__tree {
    display: flex;
    flex-direction: column;
}

/*
 * Подвал отбит линией и подложкой — чтобы на длинном дереве было видно, что
 * список кончился, а не оборвался. Закрепить его у нижнего края нельзя
 * (см. комментарий в шаблоне), поэтому визуальная граница остаётся
 * единственным сигналом конца содержимого.
 */
.task-tab__footer {
    margin-top: 2px;
    padding-top: 12px;
    border-top: 1px solid var(--ui-color-divider-default);
}

/* На узком фрейме кнопки шапки уходят на свою строку и растягиваются. */
.task-tab--narrow .task-tab__bar {
    flex-direction: column;
    align-items: stretch;
}

.task-tab--narrow .task-tab__bar-actions {
    justify-content: space-between;
}

/* На узком и среднем фрейме дубль выгрузок встаёт своей строкой во всю ширину. */
.task-tab--narrow .task-tab__tools-exports,
.task-tab--medium .task-tab__tools-exports {
    flex-basis: 100%;
    margin-left: 0;
}
</style>
