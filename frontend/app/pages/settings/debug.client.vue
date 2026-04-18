<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame">
      <div class="ms-page-header">
        <div>
          <h1 class="ms-title">Панель отладки</h1>
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
        HTTP Запросы
      </button>
      <button 
        @click="activeTab = 'system'" 
        class="ms-tab-btn"
        :class="activeTab === 'system' ? 'ms-tab-btn-active' : ''"
      >
        Системные Логи
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
                <th>Time</th>
                <th>Method</th>
                <th>Path</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in requestLogs" :key="log.id" class="text-sm">
                <td class="whitespace-nowrap text-slate-500">{{ formatDate(log.timestamp) }}</td>
                <td class="font-mono font-bold" :class="getMethodColor(log.method)">{{ log.method }}</td>
                <td class="max-w-xs truncate font-mono text-xs" :title="log.path">{{ log.path }}</td>
                <td class="font-mono" :class="getStatusColor(log.status_code)">{{ log.status_code }}</td>
                <td class="text-slate-500">{{ log.duration_ms?.toFixed(0) }}ms</td>
                <td>
                  <button @click="openDetails(log)" class="text-xs font-medium text-lime-700 hover:text-lime-800">Details</button>
                </td>
              </tr>
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
          <div class="flex flex-wrap items-center gap-2">
            <label class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600">
              <input v-model="showNotifierLogsOnly" type="checkbox" class="rounded border-slate-300">
              Только budget-notifier
            </label>
            <B24Button
              label="Запустить Budget Notifier"
              size="sm"
              color="air-primary"
              :loading="isRunningNotifier"
              @click="runBudgetNotifier"
            />
            <B24Button label="Обновить" size="sm" @click="fetchSystem(1)" />
          </div>
        </div>

        <div
          v-if="notifierResult"
          class="mb-4 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700"
        >
          <div class="font-semibold text-slate-900">Результат Budget Notifier</div>
          <div class="mt-2 grid gap-1 text-xs text-slate-600 sm:grid-cols-3">
            <div>Проверено: {{ notifierResult.checked || 0 }}</div>
            <div>Отправлено: {{ notifierResult.sent || 0 }}</div>
            <div>Cooldown skip: {{ notifierResult.cooldown_skipped || 0 }}</div>
          </div>
          <div v-if="Array.isArray(notifierResult.events) && notifierResult.events.length > 0" class="mt-2 text-xs">
            Последние события: {{ notifierResult.events.slice(0, 3).map((event: any) => `${event.project_name} / ${event.event_code} / ${event.status}`).join('; ') }}
          </div>
        </div>

        <div class="ms-table-shell">
          <table class="ms-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Module</th>
                <th>Message</th>
                <th>Trace</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in systemLogs" :key="log.id" class="text-sm leading-tight">
                <td class="whitespace-nowrap text-slate-500">{{ formatDate(log.timestamp) }}</td>
                <td class="font-bold" :class="getLevelColor(log.level)">{{ log.level }}</td>
                <td class="text-xs text-slate-500">{{ log.module }}</td>
                <td class="max-w-md truncate" :title="log.message">{{ log.message }}</td>
                <td>
                  <button v-if="log.traceback" @click="openTrace(log)" class="text-xs font-medium text-rose-600 hover:text-rose-700">Trace</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    
      <div v-if="selectedItem" class="ms-modal-overlay" @click.self="selectedItem = null">
        <div class="ms-modal-panel flex max-h-[90vh] w-full max-w-5xl flex-col">
          <div class="ms-modal-header">
            <h3 class="text-lg font-semibold text-slate-900">Детали лога</h3>
            <button @click="selectedItem = null" class="rounded-full bg-slate-100 p-2 text-slate-500 transition hover:bg-slate-200 hover:text-slate-700">
              ✕
            </button>
          </div>

          <div class="ms-modal-body overflow-y-auto">
            <div v-if="selectedItem.request_body" class="mb-4">
              <h4 class="mb-1 text-sm font-semibold text-slate-900">Request Body</h4>
              <pre class="ms-code-block whitespace-pre-wrap">{{ parseOrRaw(selectedItem.request_body) }}</pre>
            </div>

            <div v-if="selectedItem.response_body" class="mb-4">
              <h4 class="mb-1 text-sm font-semibold text-slate-900">Response Body</h4>
              <pre class="ms-code-block whitespace-pre-wrap">{{ parseOrRaw(selectedItem.response_body) }}</pre>
            </div>

            <div v-if="selectedItem.traceback" class="mb-4">
              <h4 class="mb-1 text-sm font-semibold text-rose-700">Traceback</h4>
              <pre class="overflow-x-auto whitespace-pre-wrap rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-900 shadow-sm">{{ selectedItem.traceback }}</pre>
            </div>

            <pre class="ms-code-block mt-4 whitespace-pre-wrap font-mono">{{ JSON.stringify(selectedItem, null, 2) }}</pre>
          </div>

          <div class="ms-modal-footer flex justify-end">
            <B24Button label="Закрыть" color="default" @click="selectedItem = null" />
          </div>
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
const isRunningNotifier = ref(false)
const notifierResult = ref<any | null>(null)
const showNotifierLogsOnly = ref(false)

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
    const res = await api.getSystemLogs(page, 50, {
      module: showNotifierLogsOnly.value ? 'project_budget_notifier' : undefined,
    })
    systemLogs.value = res.items
  } catch (e) {
    console.error(e)
  }
}

const runBudgetNotifier = async () => {
  isRunningNotifier.value = true
  try {
    notifierResult.value = await api.runProjectBudgetNotifier({})
    await fetchSystem(1)
  } catch (e) {
    console.error(e)
  } finally {
    isRunningNotifier.value = false
  }
}

onMounted(() => {
  fetchRequests()
  fetchSystem()
})

watch(showNotifierLogsOnly, () => {
  fetchSystem(1)
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
