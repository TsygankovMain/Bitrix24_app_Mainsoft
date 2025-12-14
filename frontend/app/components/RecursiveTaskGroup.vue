<script setup lang="ts">
import { defineProps, defineEmits } from 'vue'

const props = defineProps<{
    node: any,
    clientHourRate: number,
    users: Record<string, string>,
    openTaskIds: Set<string>
}>()

const emit = defineEmits(['toggle', 'toggleHours'])

const formatCurrency = (val: number) => val.toLocaleString('ru-RU', { style: 'currency', currency: 'RUB' });
const formatDate = (d: string) => d ? new Date(d).toLocaleDateString('ru-RU') : '-';
</script>

<template>
    <div class="bg-white border rounded-lg overflow-hidden shadow-sm my-2">
        <!-- Group Header -->
        <div class="p-3 bg-slate-50 border-b flex justify-between items-center">
             <div @click="emit('toggle', node.taskId)" class="cursor-pointer flex-1">
                 <h3 class="font-bold text-slate-900 text-sm pl-2 border-l-2 border-purple-500 ml-1">
                    {{ node.taskTitle }}
                 </h3>
                 <p class="text-xs text-slate-500 pl-4">ID: {{ node.taskId }}</p>
             </div>
             
             <div class="text-right flex gap-4 items-center">
                <div v-if="clientHourRate > 0" class="border-r pr-4">
                     <p class="font-bold text-sm">{{ formatCurrency(node.cumulativeConsidered * clientHourRate) }}</p>
                </div>
                <div>
                     <!-- Simple stats for compact view -->
                     <span class="text-xs text-green-600 font-bold mr-2">{{ node.cumulativeConsidered.toFixed(2) }}</span>
                     <span class="text-xs text-red-600 font-bold">{{ node.cumulativeUnconsidered.toFixed(2) }}</span>
                </div>
                 <button @click="emit('toggle', node.taskId)" class="text-slate-400 hover:text-slate-600">
                    {{ openTaskIds.has(node.taskId) ? '▲' : '▼' }}
                 </button>
             </div>
        </div>

        <!-- Items & Children -->
        <div v-if="openTaskIds.has(node.taskId)">
             <!-- Direct Items -->
             <div v-for="item in node.items" :key="item.id" class="p-2 pl-6 border-t flex justify-between items-start hover:bg-slate-50 text-sm">
                 <div>
                     <p class="font-medium text-slate-800">{{ item.title || 'Без названия' }}</p>
                     <p class="text-xs text-slate-400">
                         {{ users[item.ufCrm87_1761919601] || 'Неизвестно' }} • {{ formatDate(item.createdTime) }}
                     </p>
                 </div>
                 <div class="flex items-center gap-2">
                    <span :class="{'text-green-600': (item.ufCrm87_1763717129 === 'Y' || item.ufCrm87_1763717129 === true), 'text-red-600': !(item.ufCrm87_1763717129 === 'Y' || item.ufCrm87_1763717129 === true)}" class="font-bold">
                        {{ parseFloat(item.ufCrm87_1761919617 || 0).toFixed(2) }}
                    </span>
                    <button @click="emit('toggleHours', item.id)" class="text-xs text-blue-500 hover:underline">
                        switch
                    </button>
                 </div>
             </div>
             
             <!-- Children -->
             <div v-if="node.children && node.children.length" class="pl-4 border-t bg-slate-50 p-2">
                 <RecursiveTaskGroup 
                    v-for="child in node.children" 
                    :key="child.taskId" 
                    :node="child" 
                    :clientHourRate="clientHourRate" 
                    :users="users" 
                    :openTaskIds="openTaskIds" 
                    @toggle="(id) => emit('toggle', id)" 
                    @toggleHours="(id) => emit('toggleHours', id)" 
                 />
             </div>
        </div>
    </div>
</template>
