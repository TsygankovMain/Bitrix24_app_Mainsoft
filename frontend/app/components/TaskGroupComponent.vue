<script setup lang="ts">
const props = defineProps<{
    task: any
    level: number
    clientHourRate: number
    expandedTasks: Set<string>
    currentEditingId: string | null
}>()

const emit = defineEmits<{
    toggle: [taskId: string]
    select: [item: any]
    createForTask: [taskId: string]
    delete: [item: any]
}>()

const isExpanded = computed(() => props.expandedTasks.has(props.task.taskId))

const totalClientAmount = computed(() => {
    return (props.task.cumulativeConsidered * props.clientHourRate).toLocaleString('ru-RU', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
    })
})

function toggleTask() {
    emit('toggle', props.task.taskId)
}

function selectItem(item: any) {
    emit('select', item)
}

function createForTask() {
    emit('createForTask', props.task.taskId)
}

function deleteItem(item: any) {
    emit('delete', item)
}
</script>

<template>
<div :style="{ marginLeft: level > 0 ? `${level}rem` : '0' }">
    <div class="task-group-card">
        <!-- TASK HEADER -->
        <div @click="toggleTask" class="task-group-header">
            <div class="flex-1 min-w-0">
                <h3 class="text-sm font-bold text-slate-900 truncate">
                    <span v-if="level > 0" class="font-normal text-lime-700">[Подзадача] </span>
                    {{ task.taskTitle }}
                </h3>
                <p class="text-xs text-slate-600 mt-1">ID: {{ task.taskId }}</p>
            </div>
            <div class="flex items-center gap-4 ml-4 text-right shrink-0">
                <div v-if="clientHourRate > 0" class="border-r pr-4 border-slate-200">
                    <p class="text-xs text-slate-500">Сумма для клиента</p>
                    <p class="text-sm font-bold text-slate-800">{{ totalClientAmount }} руб.</p>
                </div>
                <div>
                    <p class="text-xs text-teal-700">Учтено (всего)</p>
                    <p class="text-sm font-bold text-slate-800">{{ task.cumulativeConsidered.toFixed(2) }} ч</p>
                    <p v-if="task.children.length > 0 && task.totalConsidered > 0" class="text-xs text-slate-500 italic">
                        в т.ч. своих: {{ task.totalConsidered.toFixed(2) }} ч
                    </p>
                </div>
                <div>
                    <p class="text-xs text-rose-600">Не учтено (всего)</p>
                    <p class="text-sm font-bold text-slate-800">{{ task.cumulativeUnconsidered.toFixed(2) }} ч</p>
                    <p v-if="task.children.length > 0 && task.totalUnconsidered > 0" class="text-xs text-slate-500 italic">
                        в т.ч. своих: {{ task.totalUnconsidered.toFixed(2) }} ч
                    </p>
                </div>
                <div class="flex flex-col items-center gap-1">
                    <button @click.stop="createForTask" title="Отразить время" class="task-group-create-btn">
                        <span class="material-symbols-outlined text-sm">add_circle</span>
                        Отразить
                    </button>
                    <button @click.stop="toggleTask" title="Развернуть/Свернуть" class="rounded-full p-1 transition hover:bg-slate-200">
                        <span class="material-symbols-outlined text-slate-500 transition-transform" :class="{ 'rotate-180': isExpanded }">expand_more</span>
                    </button>
                </div>
            </div>
        </div>

        <!-- ITEMS & CHILDREN -->
        <div v-if="isExpanded">
            <!-- Items (compact rows) -->
            <div
                v-for="item in task.items"
                :key="item.id"
                @click="selectItem(item)"
                class="task-group-row"
                :class="currentEditingId === item.id ? 'task-group-row-active' : ''"
                style="min-height: 34px;"
            >
                <!-- Indicator dot -->
                <span
                    class="w-2 h-2 rounded-full shrink-0"
                    :class="item.isConsidered ? 'bg-emerald-500' : 'bg-rose-400'"
                ></span>

                <!-- Description -->
                <span class="flex-1 text-sm text-slate-700 truncate" :title="item.description || ''">
                    {{ item.description || '—' }}
                </span>

                <!-- Employee + Date (muted, compact) -->
                <span class="hidden md:flex items-center gap-1.5 text-xs text-slate-400 shrink-0 w-48">
                    <span class="truncate max-w-[110px]">{{ item.employeeName }}</span>
                    <span class="text-slate-300">·</span>
                    <span class="whitespace-nowrap">{{ new Date(item.date || item.createdTime).toLocaleDateString('ru-RU') }}</span>
                </span>

                <!-- Hours -->
                <span
                    class="text-sm font-bold w-14 text-right shrink-0"
                    :class="item.isConsidered ? 'text-emerald-600' : 'text-slate-400'"
                >
                    {{ item.hours.toFixed(2) }}ч
                </span>

                <!-- Edit button (hover only) -->
                <button
                    @click.stop="selectItem(item)"
                    class="task-group-action-btn"
                    title="Редактировать"
                >
                    <span class="material-symbols-outlined text-base leading-none">edit</span>
                </button>

                <!-- Delete button (hover only) -->
                <button
                    @click.stop="deleteItem(item)"
                    class="task-group-delete-btn"
                    title="Удалить запись"
                >
                    <span class="material-symbols-outlined text-base leading-none">delete</span>
                </button>
            </div>

            <!-- Children -->
            <div v-if="task.children.length > 0" class="border-t border-slate-200 bg-slate-50/80 p-2 space-y-2">
                <TaskGroupComponent 
                    v-for="child in task.children" 
                    :key="child.taskId"
                    :task="child"
                    :level="level + 1"
                    :clientHourRate="clientHourRate"
                    :expandedTasks="expandedTasks"
                    :currentEditingId="currentEditingId"
                    @toggle="(id) => emit('toggle', id)"
                    @select="(item) => emit('select', item)"
                    @createForTask="(taskId) => emit('createForTask', taskId)"
                    @delete="(item) => emit('delete', item)"
                />
            </div>
        </div>
    </div>
</div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

.task-group-card {
    margin-bottom: 14px;
    overflow: hidden;
    border: 1px solid rgba(216, 226, 238, 0.95);
    border-radius: 22px;
    background: #fff;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
}

.task-group-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    width: 100%;
    padding: 14px 16px;
    border-bottom: 1px solid rgba(226, 232, 240, 0.95);
    background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.88));
    cursor: pointer;
    transition: 180ms ease;
}

.task-group-header:hover {
    background: linear-gradient(180deg, rgba(246, 255, 223, 0.96), rgba(241, 245, 249, 0.88));
}

.task-group-create-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border-radius: 12px;
    background: #b7ea2c;
    color: #0f172a;
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 700;
    transition: 180ms ease;
}

.task-group-create-btn:hover {
    background: #c7f04f;
}

.task-group-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    border-top: 1px solid rgba(241, 245, 249, 0.95);
    background: #fff;
    cursor: pointer;
    transition: 180ms ease;
}

.task-group-row:hover {
    background: rgba(236, 252, 203, 0.35);
}

.task-group-row-active {
    background: rgba(236, 252, 203, 0.55);
    box-shadow: inset 3px 0 0 #84cc16;
}

.task-group-action-btn {
    padding: 4px;
    border-radius: 10px;
    color: #cbd5e1;
    opacity: 0;
    transition: 180ms ease;
    flex-shrink: 0;
}

.task-group-row:hover .task-group-action-btn {
    opacity: 1;
}

.task-group-action-btn:hover {
    color: #65a30d;
    background: rgba(217, 249, 157, 0.55);
}

.task-group-delete-btn {
    padding: 4px;
    border-radius: 10px;
    color: #cbd5e1;
    opacity: 0;
    transition: 180ms ease;
    flex-shrink: 0;
}

.task-group-row:hover .task-group-delete-btn {
    opacity: 1;
}

.task-group-delete-btn:hover {
    color: #e11d48;
    background: rgba(255, 228, 230, 0.95);
}
</style>
