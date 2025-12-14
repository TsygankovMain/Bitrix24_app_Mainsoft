<script setup lang="ts">
import { } from 'vue'

const props = defineProps<{
    node: any,
    clientHourRate: number,
    users: Record<string, string>,
    openTaskIds: Set<string>,
    selectedTaskId?: string | null
}>()

const emit = defineEmits(['toggle', 'toggleHours', 'select'])

const formatCurrency = (val: number) => val.toLocaleString('ru-RU', { style: 'currency', currency: 'RUB' });
const formatDate = (d: string) => d ? new Date(d).toLocaleDateString('ru-RU') : '-';
</script>

<template>
    <div 
        class="bg-white border rounded-lg overflow-hidden shadow-sm my-2 transition-shadow hover:shadow-md"
        :class="{'ring-2 ring-blue-500 ring-offset-2': selectedTaskId === node.taskId}"
    >
        <!-- Group Header -->
        <div class="p-3 bg-slate-50 border-b flex justify-between items-center group">
             <div @click="emit('toggle', node.taskId)" class="cursor-pointer flex-1 flex items-center gap-2">
                 <span class="text-slate-400 transform transition-transform" :class="{'rotate-180': openTaskIds.has(node.taskId)}">▼</span>
                 <div>
                     <h3 class="font-bold text-slate-900 text-sm group-hover:text-blue-600 transition-colors">
                        {{ node.taskTitle }}
                     </h3>
                     <p class="text-[10px] text-slate-400">ID: {{ node.taskId }}</p>
                 </div>
             </div>
             
             <div class="flex items-center gap-3">
                 <div class="text-right hidden sm:block">
                     <span class="text-green-600 font-bold block text-sm">{{ node.cumulativeConsidered.toFixed(2) }}</span>
                 </div>
                 
                 <button 
                    @click="emit('select', node.taskId, node.taskTitle)"
                    class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                    :class="selectedTaskId === node.taskId ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-300 hover:border-blue-400 hover:text-blue-500'"
                 >
                    {{ selectedTaskId === node.taskId ? 'Выбрано' : 'Выбрать' }}
                 </button>
             </div>
        </div>

        <!-- Items & Children -->
        <div v-if="openTaskIds.has(node.taskId)">
             <!-- Direct Items -->
             <div v-for="item in node.items" :key="item.id" class="p-2 pl-6 border-t flex justify-between items-start hover:bg-slate-50 text-sm">
                 <div>
                     <p class="font-medium text-slate-800">{{ item.title || 'Без названия' }}</p>
                     <p class="text-[10px] text-slate-400">
                         {{ users[item.ufCrm87_1761919601] || 'Неизвестно' }} • {{ formatDate(item.createdTime) }}
                     </p>
                 </div>
                 <div class="flex items-center gap-2">
                    <span :class="{'text-green-600': (item.ufCrm87_1763717129 === 'Y' || item.ufCrm87_1763717129 === true), 'text-red-600': !(item.ufCrm87_1763717129 === 'Y' || item.ufCrm87_1763717129 === true)}" class="font-bold">
                        {{ parseFloat(item.ufCrm87_1761919617 || 0).toFixed(2) }}
                    </span>
                    <button @click="emit('toggleHours', item.id)" class="text-[10px] bg-slate-100 text-slate-600 px-2 py-1 rounded hover:bg-slate-200">
                        Изменить
                    </button>
                 </div>
             </div>
             
             <!-- Children -->
             <div v-if="node.children && node.children.length" class="pl-4 border-t bg-slate-50 p-2 space-y-2">
                 <RecursiveTaskGroup 
                    v-for="child in node.children" 
                    :key="child.taskId" 
                    :node="child" 
                    :clientHourRate="clientHourRate" 
                    :users="users" 
                    :openTaskIds="openTaskIds" 
                    :selectedTaskId="selectedTaskId"
                    @toggle="(id) => emit('toggle', id)" 
                    @toggleHours="(id) => emit('toggleHours', id)" 
                    @select="(id, title) => emit('select', id, title)"
                 />
             </div>
        </div>
    </div>
</template>
