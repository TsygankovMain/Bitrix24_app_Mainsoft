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
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-900/40 backdrop-blur-sm p-4">
      <!-- Overlay click to close -->
      <div class="absolute inset-0" @click="close"></div>

      <div class="modal bg-white dark:bg-gray-900 shadow-xl relative z-10">
        <!-- Header -->
        <div class="modal__header bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
          <h2 class="text-lg font-bold text-gray-900 dark:text-gray-100" id="slide-over-title">
            Инструкция: Учёт времени
          </h2>
          <button 
            type="button" 
            class="text-gray-400 hover:text-gray-500 focus:outline-none"
            @click="close"
          >
            <span class="sr-only">Закрыть</span>
            <span class="material-symbols-outlined">close</span>
          </button>
        </div>
            
        <!-- Body -->
        <div class="modal__body">
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
          </div>
        </div>

        <!-- Footer -->
        <div class="modal__footer border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex justify-end">
           <button @click="close" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Закрыть инструкцию</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Modal Adaptive Styles */
.modal {
  width: min(92vw, 720px);
  max-height: 85vh;
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal__header,
.modal__footer {
  padding: 16px 20px;
}

.modal__body {
  padding: 16px 20px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .modal {
    width: 94vw;
    max-height: 90vh;
    border-radius: 12px;
  }

  .modal__header,
  .modal__body,
  .modal__footer {
    padding: 12px 14px;
  }
}
</style>
