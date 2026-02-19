<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <div v-if="modelValue" class="fixed inset-0 z-50 overflow-hidden" aria-labelledby="slide-over-title" role="dialog" aria-modal="true">
    <div class="absolute inset-0 overflow-hidden">
      <!-- Background overlay -->
      <div 
        class="absolute inset-0 bg-gray-500 bg-opacity-75 transition-opacity" 
        @click="close"
        aria-hidden="true"
      ></div>

      <div class="pointer-events-none fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div class="pointer-events-auto w-screen max-w-md">
          <div class="flex h-full flex-col overflow-y-scroll bg-white dark:bg-gray-900 shadow-xl">
            <div class="px-4 py-6 sm:px-6 border-b border-gray-200 dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-900 z-10">
              <div class="flex items-start justify-between">
                <h2 class="text-lg font-medium text-gray-900 dark:text-gray-100" id="slide-over-title">
                  Инструкция: Учёт времени
                </h2>
                <div class="ml-3 flex h-7 items-center">
                  <button 
                    type="button" 
                    class="rounded-md bg-white dark:bg-gray-900 text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                    @click="close"
                  >
                    <span class="sr-only">Закрыть</span>
                    <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
            
            <div class="relative mt-6 flex-1 px-4 sm:px-6 pb-10">
              
              <div class="space-y-8">
                <!-- 1. Интерфейс -->
                <section class="space-y-2">
                  <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">1. Интерфейс вкладки</h3>
                  <p class="text-sm text-gray-700 dark:text-gray-300">
                    Вкладка <strong>«Учёт часов»</strong> показывает структуру подзадач и позволяет вносить время.
                  </p>
                  
                  <div class="border-2 border-dashed border-gray-300 rounded-xl p-4 bg-gray-50 flex flex-col items-center justify-center text-center">
                     <div class="mb-2 text-2xl">📸</div>
                     <p class="font-medium text-gray-500 text-xs">Скриншот общего вида</p>
                  </div>

                  <ul class="list-disc list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300 ml-2">
                    <li><strong>Дерево задач:</strong> Текущая задача и подзадачи.</li>
                    <li><strong>Часы:</strong> План / Факт справа от каждой задачи.</li>
                    <li><strong>Итоги:</strong> Внизу суммарное время.</li>
                  </ul>
                </section>

                <!-- 2. Добавление записи -->
                <section class="space-y-2">
                  <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">2. Как внести время</h3>
                  <ol class="list-decimal list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300 ml-2">
                    <li>Нажмите <strong>«Отразить»</strong> (синий плюс).</li>
                    <li>Заполните поля:
                        <ul class="list-disc list-inside ml-4 mt-1 text-gray-600">
                            <li><strong>Описание:</strong> Что сделано.</li>
                            <li><strong>Часы:</strong> Затраченное время.</li>
                            <li><strong>Учитывать:</strong> Галочка (влияет на отчеты).</li>
                        </ul>
                    </li>
                    <li>Нажмите <strong>«Сохранить»</strong>.</li>
                  </ol>

                  <div class="border-2 border-dashed border-gray-300 rounded-xl p-4 bg-gray-50 flex flex-col items-center justify-center text-center">
                     <div class="mb-2 text-2xl">📸</div>
                     <p class="font-medium text-gray-500 text-xs">Скриншот формы добавления</p>
                  </div>
                </section>

                <!-- 3. Разделение записи -->
                <section class="space-y-2">
                  <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">3. Разделение записи (Split)</h3>
                  <p class="text-sm text-gray-700 dark:text-gray-300">
                    Если нужно разделить запись (частично оплачивается/нет):
                  </p>
                  <ol class="list-decimal list-inside space-y-1 text-sm text-gray-700 dark:text-gray-300 ml-2">
                    <li>Нажмите на запись в списке.</li>
                    <li>В блоке <strong>«Разделение (Split)»</strong> введите часы для отделения.</li>
                    <li>Выберите «Учитывать?».</li>
                    <li>Нажмите <strong>«Разделить»</strong>.</li>
                  </ol>

                  <div class="border-2 border-dashed border-gray-300 rounded-xl p-4 bg-gray-50 flex flex-col items-center justify-center text-center">
                     <div class="mb-2 text-2xl">📸</div>
                     <p class="font-medium text-gray-500 text-xs">Скриншот блока Split</p>
                  </div>
                  
                  <div class="bg-blue-50 border-l-4 border-blue-500 p-3 rounded-r">
                    <p class="text-xs text-blue-700">
                      Старая запись уменьшится, появится новая. Общая сумма не изменится.
                    </p>
                  </div>
                </section>
                
                <div class="pt-4 border-t text-center">
                    <button @click="close" class="text-blue-600 hover:text-blue-800 text-sm font-medium">Закрыть инструкцию</button>
                </div>
              </div>

            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
