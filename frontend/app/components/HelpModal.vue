<script setup lang="ts">
const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="ms-modal-overlay" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="absolute inset-0" @click="emit('close')" />

    <div class="fixed inset-0 z-10 overflow-y-auto">
      <div class="flex min-h-full items-center justify-center p-4 text-center sm:p-0">
        <div class="ms-modal-panel relative w-full max-w-lg text-left sm:my-8 sm:max-w-2xl">
          
          <!-- Close Button -->
          <div class="absolute right-0 top-0 hidden pr-4 pt-4 sm:block">
            <button type="button" class="rounded-full bg-slate-100 p-2 text-slate-400 transition hover:bg-slate-200 hover:text-slate-500 focus:outline-none" @click="emit('close')">
              <span class="sr-only">Close</span>
              <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          <!-- Content -->
          <div class="ms-modal-body sm:flex sm:items-start">
            <div class="mt-3 w-full text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-base font-semibold leading-6 text-slate-900" id="modal-title">
                Как работать с модулем "Учет часов"
              </h3>
              <div class="mt-4 space-y-4 text-left text-sm text-slate-500">
                  <p>Этот модуль позволяет учитывать затраченное время на задачу и её подзадачи.</p>
                  
                  <h4 class="font-bold text-slate-700">1. Обзор ситуации</h4>
                  <ul class="list-disc pl-5 space-y-1">
                      <li><strong>Сводка сверху:</strong> Показывает общее время, оплачиваемое (для клиента) и внутреннее.</li>
                      <li><strong>Дерево задач:</strong> Вы видите текущую задачу и все вложенные подзадачи с итогами по каждой.</li>
                  </ul>

                  <h4 class="font-bold text-slate-700">2. Добавление и редактирование</h4>
                  <ul class="list-disc pl-5 space-y-1">
                      <li>Нажмите <strong>(+)</strong> напротив задачи, чтобы добавить часы.</li>
                      <li>Кликните на существующую запись, чтобы <strong>изменить</strong> часы, комментарий или дату.</li>
                  </ul>

                  <h4 class="font-bold text-slate-700">3. Статусы (Billable)</h4>
                  <p>Используйте переключатель, чтобы отметить часы как <strong>Оплачиваемые</strong> (зеленый) или <strong>Внутренние</strong> (серый).</p>

                  <h4 class="font-bold text-slate-700">4. Отчеты</h4>
                  <p>Кнопка <strong>"В отчет"</strong> перенесет все оплачиваемые часы в стандартный отчет Битрикс24 (Elapsed Time) для биллинга.</p>
              </div>
            </div>
          </div>
          
          <!-- Footer -->
          <div class="ms-modal-footer mt-5 sm:mt-4 sm:flex sm:flex-row-reverse">
            <button type="button" class="inline-flex w-full justify-center rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 sm:ml-3 sm:w-auto" @click="emit('close')">
              Понятно
            </button>
          </div>

        </div>
      </div>
    </div>
  </Teleport>
</template>
