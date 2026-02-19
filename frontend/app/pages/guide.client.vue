<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()
</script>

<template>
  <div class="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-screen w-full flex-1 min-w-0">
    <div class="w-full max-w-full">
      <!-- Header -->
      <div class="mb-8">
        <B24Button label="Назад к меню" color="link" @click="router.push('/')" class="mb-4 pl-0" />
        <div class="flex items-center gap-4">
            <div class="p-3 bg-purple-100 rounded-full text-purple-600">
                <BookOpen1Icon class="w-8 h-8" />
            </div>
            <h1 class="text-3xl font-bold text-gray-900 dark:text-gray-100">Руководство пользователя</h1>
        </div>
        <p class="mt-4 text-lg text-gray-600 dark:text-gray-400">
          Полное руководство по работе с учетом трудозатрат в задачах Битрикс24.
        </p>
      </div>

      <div class="space-y-16 max-w-7xl">
        
        <!-- Section 1: Interface -->
        <section class="space-y-6">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">1. Интерфейс вкладки «Учёт часов»</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Вкладка <strong>«Учёт часов»</strong> находится внутри каждой задачи. Она показывает структуру подзадач и позволяет вносить время.
          </p>
          
          <!-- Mockup: Interface -->
          <div class="border rounded-xl shadow-lg bg-white overflow-hidden max-w-4xl">
              <!-- Fake Header -->
              <div class="bg-slate-100 px-4 py-3 border-b flex items-center justify-between">
                  <div class="font-semibold text-slate-700">Учет часов</div>
                  <div class="flex gap-4 text-sm text-slate-500">
                      <span>План: 8ч</span>
                      <span>Факт: 5ч</span>
                  </div>
              </div>
              <!-- Fake Tree Table -->
              <div class="p-0">
                  <table class="w-full text-sm text-left">
                      <thead class="text-xs text-slate-500 uppercase bg-slate-50 border-b">
                          <tr>
                              <th class="px-4 py-3">Задача</th>
                              <th class="px-4 py-3 w-32 text-center">Часы</th>
                              <th class="px-4 py-3 w-20"></th>
                          </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100">
                          <tr class="bg-slate-50/50">
                              <td class="px-4 py-3 font-medium text-slate-900">
                                  <span class="mr-2">▼</span> Разработка сайта
                              </td>
                              <td class="px-4 py-3 text-center font-bold text-blue-600">5:00</td>
                              <td class="px-4 py-3"></td>
                          </tr>
                          <tr>
                              <td class="px-4 py-3 pl-8 text-slate-700">
                                  Frontend (Верстка)
                              </td>
                              <td class="px-4 py-3 text-center">3:00</td>
                              <td class="px-4 py-3 text-right">
                                  <button class="px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200 text-xs font-bold">+ Отразить</button>
                              </td>
                          </tr>
                          <tr>
                              <td class="px-4 py-3 pl-8 text-slate-700">
                                  Backend (API)
                              </td>
                              <td class="px-4 py-3 text-center">2:00</td>
                              <td class="px-4 py-3 text-right">
                                  <button class="px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200 text-xs font-bold">+ Отразить</button>
                              </td>
                          </tr>
                      </tbody>
                      <tfoot class="bg-slate-50 border-t">
                          <tr>
                              <td class="px-4 py-3 font-bold text-slate-900 text-right">ИТОГО:</td>
                              <td class="px-4 py-3 font-bold text-center text-slate-900">5:00</td>
                              <td></td>
                          </tr>
                      </tfoot>
                  </table>
              </div>
          </div>

          <ul class="list-disc list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li><strong>Дерево задач:</strong> Показывает текущую задачу и все её подзадачи.</li>
            <li><strong>Часы (Факт / План):</strong> Справа от каждой задачи видно, сколько времени уже внесено.</li>
            <li><strong>Итоги:</strong> В самом низу — суммарное время по всему дереву.</li>
          </ul>
        </section>

        <!-- Section 2: Adding Time -->
        <section class="space-y-6">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">2. Как внести время</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Чтобы добавить запись о работе:
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите кнопку <strong>«Отразить»</strong> (синий плюс) напротив нужной задачи.</li>
            <li>Откроется форма (справа).</li>
            <li>Заполните поля (Описание, Часы и др.).</li>
            <li>Нажмите <strong>«Сохранить»</strong>.</li>
          </ol>

          <!-- Mockup: Add Form -->
          <div class="border rounded-xl shadow-lg bg-white overflow-hidden max-w-sm ml-4">
              <div class="p-4 border-b bg-slate-50 flex justify-between items-center">
                  <h3 class="font-bold text-slate-800">Новая запись</h3>
                  <span class="text-slate-400">✕</span>
              </div>
              <div class="p-4 space-y-4">
                  <div>
                      <label class="text-xs font-bold text-slate-500 uppercase">Описание</label>
                      <textarea class="w-full border rounded p-2 text-sm mt-1" rows="2" disabled>Разработка компонента списка задач</textarea>
                  </div>
                  <div class="flex gap-2">
                      <div class="w-24">
                          <label class="text-xs font-bold text-slate-500 uppercase">Часы</label>
                          <input type="text" class="w-full border rounded p-2 text-sm mt-1" value="2" disabled>
                      </div>
                      <div class="flex-1">
                           <label class="text-xs font-bold text-slate-500 uppercase">Дата</label>
                           <input type="date" class="w-full border rounded p-2 text-sm mt-1" disabled>
                      </div>
                  </div>
                  <div class="flex items-center gap-2">
                      <input type="checkbox" checked disabled>
                      <label class="text-sm text-slate-700">Учитывать в отчете</label>
                  </div>
                  <div class="pt-2">
                      <button class="w-full py-2 bg-blue-600 text-white rounded font-semibold text-sm hover:cursor-default">Сохранить</button>
                  </div>
              </div>
          </div>
        </section>

        <!-- Section 3: Splitting Time -->
        <section class="space-y-6">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">3. Разделение записи (Split)</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Если нужно разделить одну запись на две (например, часть времени оплачивается, а часть нет):
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите на существующую запись в списке (дереве).</li>
            <li>В форме редактирования найдите блок <strong>«Разделение (Split)»</strong>.</li>
            <li>Введите количество часов для отделения.</li>
            <li>Нажмите <strong>«Разделить»</strong>.</li>
          </ol>

          <!-- Mockup: Split -->
          <div class="border rounded-xl shadow-lg bg-white overflow-hidden max-w-sm ml-4">
              <div class="p-4 bg-orange-50 border-b border-orange-100">
                  <h3 class="font-bold text-orange-800 flex items-center gap-2">
                       <span>✂️</span> Разделение (Split)
                  </h3>
              </div>
              <div class="p-4 space-y-4">
                   <p class="text-xs text-slate-500">Отделить от текущей записи (5:00):</p>
                   <div class="flex gap-2">
                       <input type="text" class="w-24 border rounded p-2 text-sm" value="2.5" disabled>
                       <button class="flex-1 bg-orange-100 text-orange-700 border border-orange-200 rounded font-semibold text-sm hover:cursor-default">Разделить</button>
                   </div>
                   <div class="flex items-center gap-2">
                      <input type="checkbox" disabled>
                      <label class="text-sm text-slate-700">Учитывать новую запись?</label>
                  </div>
              </div>
          </div>
          
          <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r mt-4">
            <p class="text-blue-700 text-sm">
              <strong>Обратите внимание:</strong> При разделении старая запись уменьшается, создается новая. Общая сумма часов не меняется.
            </p>
          </div>
        </section>

        <!-- Section 4: Configuration Info -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">4. Настройка и Данные</h2>
             <p class="text-gray-700 dark:text-gray-300">
               Для работы приложения необходимо создать источник данных (Смарт-процесс) и поля.
               Это делается в разделе <span @click="router.push('/settings/mapping')" class="text-blue-600 cursor-pointer hover:underline font-medium">Настройки -> Маппинг</span>.
             </p>
             <p class="text-gray-700 dark:text-gray-300">
               Также в настройках можно задать <strong>Стоимость часа (по умолчанию)</strong>, которая будет применяться для всех новых записей.
             </p>
        </section>

      </div>
    </div>
  </div>
</template>
