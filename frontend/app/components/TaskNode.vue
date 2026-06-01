<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
    node: any
    rate: number
    level?: number
}>()

const emit = defineEmits(['edit'])

const level = props.level || 0
const isExpanded = ref(true)

const hasChildren = computed(() => (props.node.children && props.node.children.length > 0) || (props.node.items && props.node.items.length > 0))

const indentStyle = computed(() => ({ paddingLeft: `${Math.max(0.5, level * 1.5)}rem` }))

const totalMoney = computed(() => props.node.cumulativeConsidered * props.rate)

</script>

<template>
    <div>
        <!-- ROW -->
        <div 
            class="group flex items-center gap-3 border-b border-slate-200/80 p-3 transition-colors"
            :class="level === 0 ? 'bg-slate-50/70' : 'bg-white hover:bg-blue-50/40'"
            :style="indentStyle"
        >
            <div class="flex-1 min-w-0 flex items-center gap-2">
                <button 
                    v-if="hasChildren" 
                    @click="isExpanded = !isExpanded" 
                    class="flex h-7 w-7 items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
                >
                     <span class="material-symbols-outlined">{{ isExpanded ? "expand_more" : "chevron_right" }}</span>
                </button>
                <div v-else class="w-6"></div>

                <div class="flex flex-col min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold text-sm text-slate-800 truncate" :title="node.taskTitle">{{ node.taskTitle }}</span>
                         <a :href="`/company/personal/user/0/tasks/task/view/${node.taskId}/`" target="_blank" class="text-slate-300 opacity-0 transition-opacity hover:text-[#0075ff] group-hover:opacity-100">
                            <span class="material-symbols-outlined text-xs">open_in_new</span>
                        </a>
                    </div>
                    <span class="text-[10px] text-slate-400 font-mono">ID: {{ node.taskId }}</span>
                </div>
            </div>

            <!-- STATS -->
            <div class="flex items-center gap-6 text-right shrink-0">
                <div v-if="rate > 0" class="w-24 hidden md:block">
                    <div class="text-xs text-slate-400">Сумма</div>
                    <div class="text-sm font-semibold text-slate-700">{{ totalMoney.toLocaleString('ru-RU') }} ₽</div>
                </div>

                <div class="w-20">
                    <div class="text-xs font-medium text-teal-700">Учтено</div>
                    <div class="text-sm font-bold text-slate-700">{{ node.cumulativeConsidered.toFixed(2) }} ч</div>
                </div>
                
                <div class="w-24">
                    <div class="text-xs font-medium text-rose-600/90">Не учтено</div>
                    <div class="text-sm font-medium text-slate-500">{{ node.cumulativeUnconsidered.toFixed(2) }} ч</div>
                </div>
            </div>
        </div>

        <!-- CHILDREN -->
        <div v-show="isExpanded" class="animate-slide-down">
            <!-- ITEMS -->
            <TaskItemRow 
                v-for="item in node.items" 
                :key="item.id" 
                :item="item" 
                :level="level + 1" 
                @edit="$emit('edit', $event)"
            />
            
            <!-- RECURSION -->
            <TaskNode 
                v-for="child in node.children" 
                :key="child.taskId" 
                :node="child" 
                :rate="rate" 
                :level="level + 1"
                @edit="$emit('edit', $event)"
            />
        </div>
    </div>
</template>
