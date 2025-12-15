<template>
  <div class="p-4 sm:p-6 bg-white dark:bg-gray-900 min-h-screen">
    <!-- Header -->
    <div class="flex items-center justify-between mb-8">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-gray-100">Панель отладки</h1>
      <button @click="router.push('/settings')" class="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded hover:bg-gray-200">
        Назад
      </button>
    </div>
    
    <!-- Tabs -->
    <div class="flex space-x-4 mb-6 border-b border-gray-200 dark:border-gray-700 pb-2">
      <button 
        @click="activeTab = 'requests'" 
        class="pb-2 px-1 text-sm font-medium transition-colors"
        :class="activeTab === 'requests' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
      >
        HTTP Запросы
      </button>
      <button 
        @click="activeTab = 'system'" 
        class="pb-2 px-1 text-sm font-medium transition-colors"
        :class="activeTab === 'system' ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
      >
        Системные Логи
      </button>
    </div>
    
    <!-- Requests Tab -->
    <div v-if="activeTab === 'requests'">
      <div class="mb-4 flex justify-between">
         <button @click="fetchRequests(1)" class="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded hover:bg-blue-200">Обновить</button>
      </div>
      
      <div class="overflow-x-auto border rounded-lg shadow-sm">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
           <thead class="bg-gray-50 dark:bg-gray-800">
             <tr>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Method</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Path</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
             </tr>
           </thead>
           <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
             <tr v-for="log in requestLogs" :key="log.id" class="text-sm hover:bg-gray-50">
                <td class="px-3 py-2 whitespace-nowrap text-gray-500">{{ formatDate(log.timestamp) }}</td>
                <td class="px-3 py-2 font-mono font-bold" :class="getMethodColor(log.method)">{{ log.method }}</td>
                <td class="px-3 py-2 font-mono text-xs max-w-xs truncate" :title="log.path">{{ log.path }}</td>
                <td class="px-3 py-2 font-mono" :class="getStatusColor(log.status_code)">{{ log.status_code }}</td>
                <td class="px-3 py-2 text-gray-500">{{ log.duration_ms?.toFixed(0) }}ms</td>
                <td class="px-3 py-2">
                   <button @click="openDetails(log)" class="text-blue-600 hover:text-blue-800 text-xs font-medium">Details</button>
                </td>
             </tr>
           </tbody>
        </table>
      </div>
    </div>
    
    <!-- System Tab -->
    <div v-if="activeTab === 'system'">
       <div class="mb-4 flex justify-between">
         <button @click="fetchSystem(1)" class="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded hover:bg-blue-200">Обновить</button>
      </div>
       <div class="overflow-x-auto border rounded-lg shadow-sm">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
           <thead class="bg-gray-50 dark:bg-gray-800">
             <tr>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Level</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Module</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Message</th>
               <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Trace</th>
             </tr>
           </thead>
           <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
             <tr v-for="log in systemLogs" :key="log.id" class="text-sm hover:bg-gray-50 leading-tight">
                <td class="px-3 py-2 whitespace-nowrap text-gray-500">{{ formatDate(log.timestamp) }}</td>
                <td class="px-3 py-2 font-bold" :class="getLevelColor(log.level)">{{ log.level }}</td>
                <td class="px-3 py-2 text-gray-600 text-xs">{{ log.module }}</td>
                <td class="px-3 py-2 max-w-md truncate" :title="log.message">{{ log.message }}</td>
                <td class="px-3 py-2">
                   <button v-if="log.traceback" @click="openTrace(log)" class="text-red-600 hover:text-red-800 text-xs font-medium">Trace</button>
                </td>
             </tr>
           </tbody>
        </table>
      </div>
    </div>
    
    <!-- Modal -->
    <div v-if="selectedItem" class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm" @click.self="selectedItem = null">
       <div class="bg-white dark:bg-gray-800 w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-lg p-6 shadow-xl border border-gray-200">
          <div class="flex justify-between items-center mb-4">
             <h3 class="text-xl font-bold">Детали лога</h3>
             <button @click="selectedItem = null" class="text-gray-500 hover:text-gray-700">
               ✕
             </button>
          </div>
          
          <div v-if="selectedItem.request_body" class="mb-4">
               <h4 class="font-bold text-sm mb-1">Request Body:</h4>
               <pre class="bg-gray-100 p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">{{ parseOrRaw(selectedItem.request_body) }}</pre>
          </div>
          
          <div v-if="selectedItem.response_body" class="mb-4">
                <h4 class="font-bold text-sm mb-1">Response Body:</h4>
               <pre class="bg-gray-100 p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">{{ parseOrRaw(selectedItem.response_body) }}</pre>
          </div>
          
          <div v-if="selectedItem.traceback" class="mb-4">
               <h4 class="font-bold text-sm mb-1 text-red-600">Traceback:</h4>
               <pre class="bg-red-50 text-red-900 p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">{{ selectedItem.traceback }}</pre>
          </div>

          <pre class="bg-slate-50 p-4 rounded text-xs overflow-x-auto whitespace-pre-wrap font-mono mt-4 border">{{ JSON.stringify(selectedItem, null, 2) }}</pre>
          
          <div class="mt-6 flex justify-end">
             <button @click="selectedItem = null" class="bg-gray-200 px-4 py-2 rounded hover:bg-gray-300 transition-colors text-sm">Close</button>
          </div>
       </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { useApiStore } from '~/stores/api'

const router = useRouter()
const api = useApiStore()
const activeTab = ref<'requests' | 'system'>('requests')

const requestLogs = ref<any[]>([])
const systemLogs = ref<any[]>([])
const selectedItem = ref<any>(null)

useHead({
  title: 'Панель отладки'
})

const fetchRequests = async (page = 1) => {
  try {
    const res = await api.getRequestLogs(page, 50)
    requestLogs.value = res.items
  } catch (e) {
    console.error(e)
  }
}

const fetchSystem = async (page = 1) => {
   try {
    const res = await api.getSystemLogs(page, 50)
    systemLogs.value = res.items
  } catch (e) {
    console.error(e)
  }
}

onMounted(() => {
  fetchRequests()
  fetchSystem()
})

const formatDate = (ts: string) => {
   if(!ts) return ''
   return new Date(ts).toLocaleString('ru-RU')
}

const getMethodColor = (m: string) => {
  if(m === 'GET') return 'text-green-600'
  if(m === 'POST') return 'text-blue-600'
  if(m === 'DELETE') return 'text-red-600'
  return 'text-gray-600'
}

const getStatusColor = (s: number) => {
  if(s >= 500) return 'text-red-600 font-bold'
  if(s >= 400) return 'text-orange-600'
  if(s >= 200) return 'text-green-600'
  return 'text-gray-600'
}

const getLevelColor = (l: string) => {
  if(l === 'ERROR') return 'text-red-600'
  if(l === 'WARNING') return 'text-orange-600'
  return 'text-green-600'
}

const parseOrRaw = (str: string) => {
    try {
        if(!str) return ""
        if(str.startsWith("{") || str.startsWith("[")) {
            return JSON.stringify(JSON.parse(str), null, 2)
        }
    } catch { }
    return str
}

const openDetails = (item: any) => selectedItem.value = item
const openTrace = (item: any) => selectedItem.value = { ...item }

</script>
