<script setup lang="ts">
import { onMounted, ref } from 'vue'

definePageMeta({ layout: false })

const { $initializeB24Frame } = useNuxtApp()
let $b24: any = null

const isInstalling = ref(false)
const installStatus = ref('')
const installError = ref<string | null>(null)

onMounted(async () => {
    try {
        $b24 = await $initializeB24Frame()
    } catch (e: any) {
        installError.value = 'Ошибка инициализации: ' + e.message
    }
})

async function installPlacement() {
    if (!$b24) {
        installError.value = 'Битрикс24 не инициализирован'
        return
    }

    isInstalling.value = true
    installStatus.value = 'Регистрация встройки...'
    installError.value = null

    try {
        // Get current app URL and construct handler URL
        const currentUrl = window.location.href
        const baseUrl = currentUrl.substring(0, currentUrl.lastIndexOf('/'))
        const handlerUrl = baseUrl + '/embedded'

        // Register placement
        const result = await $b24.callMethod('placement.bind', {
            PLACEMENT: 'TASK_VIEW_TAB',
            HANDLER: handlerUrl,
            TITLE: 'Учет трудозатрат',
            DESCRIPTION: 'Встройка для учета времени по задачам'
        })

        installStatus.value = '✅ Установка завершена успешно!'
        
        // Wait a bit then call installFinish
        setTimeout(() => {
            if (typeof $b24.installFinish === 'function') {
                $b24.installFinish()
            }
        }, 1500)

    } catch (e: any) {
        installError.value = 'Ошибка установки: ' + (e.message || e.toString())
        installStatus.value = ''
    } finally {
        isInstalling.value = false
    }
}
</script>

<template>
<div class="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-6">
    <div class="bg-white rounded-2xl shadow-2xl max-w-2xl w-full p-8">
        <div class="text-center mb-8">
            <div class="w-20 h-20 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-4">
                <span class="material-symbols-outlined text-white text-5xl">schedule</span>
            </div>
            <h1 class="text-3xl font-bold text-slate-900 mb-2">Учет трудозатрат</h1>
            <p class="text-slate-600">Установка встройки в карточку задачи</p>
        </div>

        <div v-if="!installStatus && !installError" class="space-y-6">
            <div class="bg-blue-50 border border-blue-200 rounded-lg p-6">
                <h2 class="font-bold text-blue-900 mb-3 flex items-center gap-2">
                    <span class="material-symbols-outlined">info</span>
                    Что будет установлено?
                </h2>
                <ul class="space-y-2 text-sm text-blue-800">
                    <li class="flex items-start gap-2">
                        <span class="material-symbols-outlined text-base mt-0.5">check_circle</span>
                        <span>Вкладка "Учет трудозатрат" в карточке каждой задачи</span>
                    </li>
                    <li class="flex items-start gap-2">
                        <span class="material-symbols-outlined text-base mt-0.5">check_circle</span>
                        <span>Иерархическое отображение задач и подзадач</span>
                    </li>
                    <li class="flex items-start gap-2">
                        <span class="material-symbols-outlined text-base mt-0.5">check_circle</span>
                        <span>Возможность редактировать записи времени без попапов</span>
                    </li>
                    <li class="flex items-start gap-2">
                        <span class="material-symbols-outlined text-base mt-0.5">check_circle</span>
                        <span>Функционал разделения записей и расчета стоимости</span>
                    </li>
                </ul>
            </div>

            <button 
                @click="installPlacement" 
                :disabled="isInstalling"
                class="w-full py-4 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-all text-lg shadow-lg shadow-blue-200 flex items-center justify-center gap-3"
            >
                <span v-if="isInstalling" class="material-symbols-outlined animate-spin">progress_activity</span>
                <span v-else class="material-symbols-outlined">download</span>
                <span>{{ isInstalling ? 'Установка...' : 'Установить встройку' }}</span>
            </button>
        </div>

        <div v-if="installStatus" class="text-center py-8">
            <div class="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <span class="material-symbols-outlined text-green-600 text-4xl">check_circle</span>
            </div>
            <h2 class="text-xl font-bold text-slate-900 mb-2">{{ installStatus }}</h2>
            <p class="text-slate-600 text-sm">Теперь вы можете открыть любую задачу и увидеть новую вкладку</p>
        </div>

        <div v-if="installError" class="bg-red-50 border border-red-200 rounded-lg p-6">
            <div class="flex items-start gap-3">
                <span class="material-symbols-outlined text-red-600 text-2xl">error</span>
                <div class="flex-1">
                    <h3 class="font-bold text-red-900 mb-1">Ошибка</h3>
                    <p class="text-red-700 text-sm">{{ installError }}</p>
                </div>
            </div>
            <button 
                @click="installError = null; installPlacement()" 
                class="mt-4 w-full py-2 bg-white border border-red-300 text-red-700 font-medium rounded-lg hover:bg-red-50"
            >
                Попробовать снова
            </button>
        </div>
    </div>
</div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}
</style>
