<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="ms-page-header">
        <div>
          <h1 class="ms-title">Диагностика системы</h1>
          <p class="ms-subtitle mt-2">История запросов, системные события и разбор ошибок.</p>
        </div>
        <B24Button label="Назад" color="link" @click="router.push('/settings')" />
      </div>

      <div class="ms-tabbar mb-6">
      <button 
        @click="activeTab = 'requests'" 
        class="ms-tab-btn"
        :class="activeTab === 'requests' ? 'ms-tab-btn-active' : ''"
      >
        Запросы
      </button>
      <button 
        @click="activeTab = 'system'" 
        class="ms-tab-btn"
        :class="activeTab === 'system' ? 'ms-tab-btn-active' : ''"
      >
        Системные события
      </button>
      </div>

      <div v-if="activeTab === 'requests'">
        <div class="ms-toolbar-muted mb-4">
          <div>
            <div class="text-sm font-semibold text-slate-900">HTTP запросы</div>
            <div class="mt-1 text-sm text-slate-500">Последние обращения frontend к backend и внешним API.</div>
          </div>
          <B24Button label="Обновить" size="sm" @click="fetchRequests(1)" />
        </div>

        <div class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Метод</th>
                <th>Путь</th>
                <th>Статус</th>
                <th>Длительность</th>
                <th>Действие</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="log in requestLogs" :key="`req-${log.id}`">
                <tr class="text-sm">
                  <td class="whitespace-nowrap text-slate-500">{{ formatDate(log.timestamp) }}</td>
                  <td class="font-mono font-bold" :class="getMethodColor(log.method)">{{ log.method }}</td>
                  <td class="max-w-xs truncate font-mono text-xs" :title="log.path">{{ log.path }}</td>
                  <td class="font-mono" :class="getStatusColor(log.status_code)">{{ log.status_code }}</td>
                  <td class="text-slate-500">{{ log.duration_ms?.toFixed(0) }}ms</td>
                  <td>
                    <button @click="toggleRequestDetails(log.id)" class="text-xs font-medium text-[#0075ff] hover:text-blue-700">
                      {{ expandedRequestId === log.id ? 'Скрыть' : 'Подробнее' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedRequestId === log.id">
                  <td colspan="6" class="bg-slate-50 p-3">
                    <div class="space-y-4">
                      <div v-if="log.request_body">
                        <h4 class="mb-1 text-sm font-semibold text-slate-900">Тело запроса</h4>
                        <pre class="ms-code-block whitespace-pre-wrap">{{ parseOrRaw(log.request_body) }}</pre>
                      </div>
                      <div v-if="log.response_body">
                        <h4 class="mb-1 text-sm font-semibold text-slate-900">Тело ответа</h4>
                        <pre class="ms-code-block whitespace-pre-wrap">{{ parseOrRaw(log.response_body) }}</pre>
                      </div>
                      <pre class="ms-code-block whitespace-pre-wrap font-mono">{{ JSON.stringify(log, null, 2) }}</pre>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    
      <div v-if="activeTab === 'system'">
        <div class="ms-toolbar-muted mb-4">
          <div>
            <div class="text-sm font-semibold text-slate-900">Системные логи</div>
            <div class="mt-1 text-sm text-slate-500">Ошибки, warning-события и ключевые сообщения приложения.</div>
          </div>
          <B24Button label="Обновить" size="sm" @click="fetchSystem(1)" />
        </div>

        <div class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Уровень</th>
                <th>Модуль</th>
                <th>Сообщение</th>
                <th>Стек</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="log in systemLogs" :key="`sys-${log.id}`">
                <tr class="text-sm leading-tight">
                  <td class="whitespace-nowrap text-slate-500">{{ formatDate(log.timestamp) }}</td>
                  <td class="font-bold" :class="getLevelColor(log.level)">{{ log.level }}</td>
                  <td class="text-xs text-slate-500">{{ log.module }}</td>
                  <td class="max-w-md truncate" :title="log.message">{{ log.message }}</td>
                  <td>
                    <button v-if="log.traceback" @click="toggleSystemDetails(log.id)" class="text-xs font-medium text-rose-600 hover:text-rose-700">
                      {{ expandedSystemId === log.id ? 'Скрыть' : 'Стек' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedSystemId === log.id">
                  <td colspan="5" class="bg-rose-50/30 p-3">
                    <div class="space-y-4">
                      <div v-if="log.traceback">
                        <h4 class="mb-1 text-sm font-semibold text-rose-700">Стек ошибки</h4>
                        <pre class="overflow-x-auto whitespace-pre-wrap rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-900 shadow-sm">{{ log.traceback }}</pre>
                      </div>
                      <pre class="ms-code-block whitespace-pre-wrap font-mono">{{ JSON.stringify(log, null, 2) }}</pre>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
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
const expandedRequestId = ref<number | string | null>(null)
const expandedSystemId = ref<number | string | null>(null)

useHead({
  title: 'Диагностика системы'
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
  return 'text-slate-600'
}

const getStatusColor = (s: number) => {
  if(s >= 500) return 'text-red-600 font-bold'
  if(s >= 400) return 'text-orange-600'
  if(s >= 200) return 'text-green-600'
  return 'text-slate-600'
}

const getLevelColor = (l: string) => {
  if(l === 'ERROR') return 'text-red-600'
  if(l === 'WARNING') return 'text-orange-600'
  return 'text-green-600'
}

const parseOrRaw = (value: unknown) => {
    try {
        if(value === null || value === undefined) return ""
        if(typeof value === 'string') {
            const str = value.trim()
            if(!str) return ""
            if(str.startsWith("{") || str.startsWith("[")) {
                return JSON.stringify(JSON.parse(str), null, 2)
            }
            return value
        }
        return JSON.stringify(value, null, 2)
    } catch { }
    return String(value ?? '')
}

const toggleRequestDetails = (id: number | string) => {
  expandedRequestId.value = expandedRequestId.value === id ? null : id
}

const toggleSystemDetails = (id: number | string) => {
  expandedSystemId.value = expandedSystemId.value === id ? null : id
}

watch(activeTab, () => {
  expandedRequestId.value = null
  expandedSystemId.value = null
})

</script>
