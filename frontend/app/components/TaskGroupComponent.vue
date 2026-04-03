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
    <div class="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden mb-4">
        <!-- TASK HEADER -->
        <div @click="toggleTask" class="w-full text-left p-3 bg-slate-50 border-b flex justify-between items-center cursor-pointer hover:bg-slate-100">
            <div class="flex-1 min-w-0">
                <h3 class="text-sm font-bold text-slate-900 truncate">
                    <span v-if="level > 0" class="font-normal text-purple-600">[Подзадача] </span>
                    {{ task.taskTitle }}
                </h3>
                <p class="text-xs text-slate-600 mt-1">ID: {{ task.taskId }}</p>
            </div>
            <div class="flex items-center gap-4 ml-4 text-right shrink-0">
                <div v-if="clientHourRate > 0" class="border-r pr-4 border-slate-200">
                    <p class="text-xs text-blue-600">Сумма для клиента</p>
                    <p class="text-sm font-bold text-slate-800">{{ totalClientAmount }} руб.</p>
                </div>
                <div>
                    <p class="text-xs text-green-600">Учтено (всего)</p>
                    <p class="text-sm font-bold text-slate-800">{{ task.cumulativeConsidered.toFixed(2) }} ч</p>
                    <p v-if="task.children.length > 0 && task.totalConsidered > 0" class="text-xs text-slate-500 italic">
                        в т.ч. своих: {{ task.totalConsidered.toFixed(2) }} ч
                    </p>
                </div>
                <div>
                    <p class="text-xs text-red-600">Не учтено (всего)</p>
                    <p class="text-sm font-bold text-slate-800">{{ task.cumulativeUnconsidered.toFixed(2) }} ч</p>
                    <p v-if="task.children.length > 0 && task.totalUnconsidered > 0" class="text-xs text-slate-500 italic">
                        в т.ч. своих: {{ task.totalUnconsidered.toFixed(2) }} ч
                    </p>
                </div>
                <div class="flex flex-col items-center gap-1">
                    <button @click.stop="createForTask" title="Отразить время" class="px-2 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold flex items-center gap-1">
                        <span class="material-symbols-outlined text-sm">add_circle</span>
                        Отразить
                    </button>
                    <button @click.stop="toggleTask" title="Развернуть/Свернуть" class="p-1 rounded-full hover:bg-slate-200">
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
                class="flex items-center gap-2 px-3 border-t border-slate-100 transition-colors cursor-pointer hover:bg-blue-50 group"
                :class="currentEditingId === item.id ? 'bg-blue-50 border-l-2 border-blue-500' : ''"
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
                    class="p-1 rounded text-slate-300 hover:text-blue-600 hover:bg-blue-100 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                    title="Редактировать"
                >
                    <span class="material-symbols-outlined text-base leading-none">edit</span>
                </button>

                <!-- Delete button (hover only) -->
                <button
                    @click.stop="deleteItem(item)"
                    class="p-1 rounded text-slate-300 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                    title="Удалить запись"
                >
                    <span class="material-symbols-outlined text-base leading-none">delete</span>
                </button>
            </div>

            <!-- Children -->
            <div v-if="task.children.length > 0" class="p-2 space-y-2 bg-slate-50 border-t">
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
</style>
