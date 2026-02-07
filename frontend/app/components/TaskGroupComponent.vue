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
                    <button @click.stop="toggleTask" title="Развернуть/Свернуть" class="p-1 rounded-full hover:bg-slate-200">
                        <span class="material-symbols-outlined text-slate-500 transition-transform" :class="{ 'rotate-180': isExpanded }">expand_more</span>
                    </button>
                </div>
            </div>
        </div>

        <!-- ITEMS & CHILDREN -->
        <div v-if="isExpanded">
            <!-- Items -->
            <div 
                v-for="item in task.items" 
                :key="item.id"
                @click="selectItem(item)"
                class="p-3 border-t transition-colors cursor-pointer hover:bg-blue-50"
                :class="{ 'bg-blue-50 border-l-4 border-blue-500': currentEditingId === item.id }"
            >
                <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-2">
                    <div class="flex-1 min-w-0">
                        <p class="font-semibold text-slate-800 truncate">{{ item.description }}</p>
                        <div class="flex items-center text-xs text-slate-500 mt-2 gap-3">
                            <div class="flex items-center">
                                <span class="material-symbols-outlined text-sm mr-1">person</span>
                                {{ item.employeeName }}
                            </div>
                            <div class="flex items-center">
                                <span class="material-symbols-outlined text-sm mr-1">calendar_today</span>
                                {{ new Date(item.date || item.createdTime).toLocaleDateString('ru-RU') }}
                            </div>
                        </div>
                    </div>
                    <div class="flex md:flex-col items-center md:items-end justify-between mt-2 md:mt-0 gap-2">
                        <div class="flex items-center gap-2 text-sm font-bold">
                            <span :class="item.isConsidered ? 'text-green-600' : 'text-red-600'">
                                {{ item.hours.toFixed(2) }}ч
                            </span>
                        </div>
                        <div class="flex gap-2">
                            <button @click.stop="selectItem(item)" class="px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800 hover:bg-blue-200">
                                <span class="material-symbols-outlined text-sm">edit</span>
                            </button>
                        </div>
                    </div>
                </div>
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
