<script setup lang="ts">
defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <div v-if="open" class="relative z-50 transition-opacity duration-300" aria-labelledby="help-modal-title" role="dialog" aria-modal="true">
    <!-- Background backdrop -->
    <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" @click="emit('close')"></div>

    <div class="fixed inset-0 z-10 overflow-y-auto">
      <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <!-- Responsive Width: w-11/12 on mobile, max-w-2xl on desktop -->
        <div class="relative transform overflow-hidden rounded-lg bg-white px-4 pb-4 pt-5 text-left shadow-xl transition-all w-11/12 sm:w-full sm:max-w-2xl sm:p-6">
          <div class="absolute right-0 top-0 hidden pr-4 pt-4 sm:block">
            <button type="button" class="rounded-md bg-white text-gray-400 hover:text-gray-500 focus:outline-none" @click="emit('close')">
              <span class="sr-only">Закрыть</span>
              <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="sm:flex sm:items-start">
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left w-full">
              <h3 class="text-base font-semibold leading-6 text-gray-900" id="help-modal-title">
                Руководство пользователя
              </h3>
              <div class="mt-4 text-sm text-gray-500 max-h-[70vh] overflow-y-auto pr-2 space-y-4">
                 
                 <section>
                    <h4 class="font-bold text-gray-900">1. Просмотр структуры</h4>
                    <p>
                        Задачи отображаются в виде дерева (Главная задача -> Подзадачи).
                        Возле каждой задачи показана статистика: <span class="font-medium text-gray-700">Всего / Оплачиваемо</span>.
                    </p>
                 </section>

                 <section>
                    <h4 class="font-bold text-gray-900">2. Добавление часов</h4>
                    <p>Наведите курсор на строку задачи и нажмите кнопку <span class="font-bold text-indigo-600">+</span>.</p>
                    <ul class="list-disc ml-5 mt-1">
                        <li>Укажите количество часов.</li>
                        <li>Добавьте описание проделанной работы.</li>
                        <li>Выберите дату (по умолчанию текущая).</li>
                        <li>Отметьте "Оплачиваемое", если часы должны быть в счете клиенту.</li>
                    </ul>
                 </section>

                 <section>
                    <h4 class="font-bold text-gray-900">3. Редактирование</h4>
                    <p>Кликните по любой записи времени, чтобы изменить часы, описание или дату.</p>
                 </section>

                 <section>
                    <h4 class="font-bold text-gray-900">4. Быстрые действия</h4>
                    <p>
                        Нажмите на иконку (Галочка/Круг) справа от записи, чтобы быстро переключить статус "Оплачиваемо" без открытия редактора.
                    </p>
                 </section>

                 <section>
                     <h4 class="font-bold text-gray-900">5. Перенос в отчет</h4>
                     <p>
                         Кнопка "Перенести в отчет" внизу отправляет все оплачиваемые часы за период в официальный отчет Битрикс24.
                     </p>
                 </section>

              </div>
            </div>
          </div>
          
          <div class="mt-5 sm:mt-6">
            <button type="button" class="inline-flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600" @click="emit('close')">
              Понятно
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
