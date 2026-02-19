<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()
</script>

<template>
  <div class="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-screen w-full flex-1 min-w-0 text-left">
    <div class="w-full space-y-24">
      
      <!-- Header -->
      <div class="mb-12 border-b pb-8">
        <B24Button label="Назад к меню" color="link" @click="router.push('/')" class="mb-4 pl-0" />
        <div class="flex items-center gap-4">
            <div class="p-4 bg-purple-100 rounded-2xl text-purple-600 shadow-sm">
                <BookOpen1Icon class="w-10 h-10" />
            </div>
            <div>
                <h1 class="text-4xl font-extrabold text-gray-900 dark:text-gray-100 tracking-tight">Руководство пользователя</h1>
                <p class="mt-2 text-xl text-gray-600 dark:text-gray-400">
                  Полная энциклопедия по работе с системой учёта трудозатрат и финансовой аналитики в Битрикс24.
                </p>
            </div>
        </div>
      </div>

      <div class="space-y-24 w-full">

        <!-- 1. Введение -->
        <section class="space-y-6 w-full">
          <div class="w-full">
            <h2 class="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-4">1. Введение</h2>
            <p class="lead text-lg text-gray-700 w-full">
              Добро пожаловать в систему «Учет трудозатрат»! Это приложение создано для того, чтобы сделать процесс фиксации рабочего времени простым, прозрачным и полезным для каждого сотрудника и руководителя.
            </p>
            <div class="grid md:grid-cols-3 gap-6 mt-8 w-full">
                <div class="p-6 bg-blue-50 rounded-xl border border-blue-100">
                    <h3 class="font-bold text-blue-900 mb-2">🎯 Точность</h3>
                    <p class="text-sm text-blue-800">Фиксируйте время именно там, где работаете — прямо внутри задач Битрикс24. Никаких сторонних таблиц.</p>
                </div>
                <div class="p-6 bg-green-50 rounded-xl border border-green-100">
                    <h3 class="font-bold text-green-900 mb-2">💰 Прозрачность</h3>
                    <p class="text-sm text-green-800">Видите, как ваши часы превращаются в деньги. Понятная система ставок и отчетов.</p>
                </div>
                <div class="p-6 bg-purple-50 rounded-xl border border-purple-100">
                    <h3 class="font-bold text-purple-900 mb-2">📊 Аналитика</h3>
                    <p class="text-sm text-purple-800">Мощные инструменты для анализа эффективности проектов и распределения ресурсов.</p>
                </div>
            </div>
          </div>
        </section>

        <!-- 2. Быстрый старт -->
        <section class="space-y-6">
           <h2 class="text-3xl font-bold text-gray-900 dark:text-gray-100 border-b pb-4">2. Быстрый старт</h2>
           <p class="text-gray-700 dark:text-gray-300">
             Если у вас мало времени, вот всё, что нужно знать, чтобы начать работу прямо сейчас:
           </p>
           
           <ol class="relative border-l border-gray-200 dark:border-gray-700 ml-4 space-y-10 mt-8">                  
              <li class="mb-10 ml-6">            
                  <span class="absolute flex items-center justify-center w-8 h-8 bg-blue-100 rounded-full -left-4 ring-8 ring-white dark:ring-gray-900 dark:bg-blue-900">
                      <span class="font-bold text-blue-800 dark:text-blue-300">1</span>
                  </span>
                  <h3 class="flex items-center mb-1 text-lg font-semibold text-gray-900 dark:text-white">Откройте задачу</h3>
                  <p class="mb-4 text-base font-normal text-gray-500 dark:text-gray-400">Перейдите в любую задачу в Битрикс24, над которой вы работаете.</p>
              </li>
              <li class="mb-10 ml-6">
                  <span class="absolute flex items-center justify-center w-8 h-8 bg-blue-100 rounded-full -left-4 ring-8 ring-white dark:ring-gray-900 dark:bg-blue-900">
                      <span class="font-bold text-blue-800 dark:text-blue-300">2</span>
                  </span>
                  <h3 class="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Найдите блок "Учёт трудозатрат"</h3>
                  <p class="text-base font-normal text-gray-500 dark:text-gray-400">В карточке задачи (среди полей или вкладок) найдите блок <strong>«Учет трудозатрат»</strong>.</p>
              </li>
              <li class="mb-10 ml-6">
                  <span class="absolute flex items-center justify-center w-8 h-8 bg-blue-100 rounded-full -left-4 ring-8 ring-white dark:ring-gray-900 dark:bg-blue-900">
                      <span class="font-bold text-blue-800 dark:text-blue-300">3</span>
                  </span>
                  <h3 class="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Нажмите "Отразить"</h3>
                  <p class="text-base font-normal text-gray-500 dark:text-gray-400">В появившейся таблице напротив нужной подзадачи нажмите синюю кнопку <strong>+ Отразить</strong>.</p>
              </li>
              <li class="ml-6">
                  <span class="absolute flex items-center justify-center w-8 h-8 bg-blue-100 rounded-full -left-4 ring-8 ring-white dark:ring-gray-900 dark:bg-blue-900">
                      <span class="font-bold text-blue-800 dark:text-blue-300">4</span>
                  </span>
                  <h3 class="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Сохраните время</h3>
                  <p class="text-base font-normal text-gray-500 dark:text-gray-400">Введите описание (что сделали) и количество часов. Нажмите <strong>Сохранить</strong>.</p>
              </li>
          </ol>
        </section>

        <!-- 3. Подробный обзор интерфейса -->
        <section class="space-y-8">
          <div class="flex items-end justify-between border-b pb-4">
               <h2 class="text-3xl font-bold text-gray-900 dark:text-gray-100">3. Интерфейс детально</h2>
               <span class="text-sm text-gray-500 uppercase tracking-wider font-medium">Модуль в задаче</span>
          </div>

          <p class="text-gray-700 dark:text-gray-300 mb-6">
            Главный экран приложения — это "Дерево задач". Оно отображает иерархию проекта: от текущей задачи вниз к подзадачам.
          </p>

          <!-- Mockup: Main Interface -->

          <div class="border rounded-xl shadow-2xl bg-white overflow-hidden ring-1 ring-slate-900/5">
              <!-- Fake Header -->
              <div class="bg-slate-50 px-6 py-4 border-b flex items-center justify-between">
                  <div>
                      <div class="font-bold text-slate-700 text-lg flex items-center gap-2">
                          <span class="text-blue-500">📦</span> Учет трудозатрат
                      </div>
                      <div class="text-xs text-slate-400 mt-1">Встройка для учета времени по задачам</div>
                  </div>
                  <div class="flex gap-6 text-sm">
                      <div class="flex flex-col items-end">
                          <span class="text-xs text-slate-400 uppercase">План по проекту</span>
                          <span class="font-bold text-slate-700">120 ч.</span>
                      </div>
                      <div class="flex flex-col items-end">
                          <span class="text-xs text-slate-400 uppercase">Факт (Всего)</span>
                          <span class="font-bold text-blue-600">45 ч.</span>
                      </div>
                  </div>
              </div>
              <!-- Fake Tree Table -->
              <div class="p-0 overflow-x-auto">
                  <table class="w-full text-sm text-left">
                      <thead class="text-xs text-slate-500 uppercase bg-slate-50/50 border-b">
                          <tr>
                              <th class="px-6 py-4 font-semibold">Структура задачи</th>
                              <th class="px-6 py-4 w-40 text-center font-semibold text-blue-600">Факт</th>
                              <th class="px-6 py-4 w-40 text-center font-semibold text-gray-500">План</th>
                              <th class="px-6 py-4 w-40">Действие</th>
                          </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100">
                          <tr class="bg-blue-50/30 hover:bg-blue-50/50 transition-colors">
                              <td class="px-6 py-4 font-bold text-slate-900 text-base">
                                  <span class="mr-2 text-slate-400">▼</span> Главная задача (Разработка)
                              </td>
                              <td class="px-6 py-4 text-center font-bold text-blue-700 text-base">5:00</td>
                              <td class="px-6 py-4 text-center text-gray-500">20:00</td>
                              <td class="px-6 py-4"></td>
                          </tr>
                          <tr class="hover:bg-gray-50 transition-colors group">
                              <td class="px-6 py-4 pl-12 text-slate-700 flex items-center gap-2">
                                  <span class="w-1 h-8 bg-gray-200 rounded-full"></span>
                                  <div>
                                      <div class="font-medium">Верстка макетов</div>
                                      <div class="text-xs text-gray-400">Отвественный: Иван И.</div>
                                  </div>
                              </td>
                              <td class="px-6 py-4 text-center font-medium">3:00</td>
                              <td class="px-6 py-4 text-center text-gray-400">10:00</td>
                              <td class="px-6 py-4 text-right">
                                  <button class="opacity-0 group-hover:opacity-100 transition-opacity px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200 text-xs font-bold shadow-sm active:scale-95 transform">+ Отразить</button>
                              </td>
                          </tr>
                          <tr class="hover:bg-gray-50 transition-colors group">
                              <td class="px-6 py-4 pl-12 text-slate-700 flex items-center gap-2">
                                   <span class="w-1 h-8 bg-gray-200 rounded-full"></span>
                                   <div>
                                      <div class="font-medium">Написание API</div>
                                      <div class="text-xs text-gray-400">Отвественный: Петр С.</div>
                                  </div>
                              </td>
                              <td class="px-6 py-4 text-center font-medium">2:00</td>
                              <td class="px-6 py-4 text-center text-gray-400">10:00</td>
                              <td class="px-6 py-4 text-right">
                                  <button class="opacity-0 group-hover:opacity-100 transition-opacity px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200 text-xs font-bold shadow-sm active:scale-95 transform">+ Отразить</button>
                              </td>
                          </tr>
                      </tbody>
                      <tfoot class="bg-gray-50 border-t">
                          <tr>
                              <td class="px-6 py-4 font-extrabold text-slate-900 text-right uppercase tracking-wider text-xs">Всего по дереву:</td>
                              <td class="px-6 py-4 font-extrabold text-center text-blue-700 text-lg">5:00</td>
                              <td class="px-6 py-4 text-center font-bold text-gray-500">40:00</td>
                              <td></td>
                          </tr>
                      </tfoot>
                  </table>
              </div>
          </div>
          
          <div class="grid md:grid-cols-2 gap-8 mt-6">
              <div>
                  <h4 class="font-bold text-lg mb-2">Основные элементы:</h4>
                  <ul class="list-disc list-inside space-y-2 text-gray-700">
                      <li><strong>Дерево (Слева):</strong> Показывает вложенность задач. Вы можете "сворачивать" и "разворачивать" ветки кликом на стрелку.</li>
                      <li><strong>Факт (Центр):</strong> Фактически затраченное и залогированное время. Жирным выделяется, если есть записи.</li>
                      <li><strong>Кнопка "+ Отразить":</strong> Появляется при наведении. Это единственная точка входа для добавления времени.</li>
                  </ul>
              </div>
              <div class="bg-yellow-50 p-6 rounded-xl border border-yellow-200">
                  <h4 class="font-bold text-yellow-800 mb-2 flex items-center gap-2">
                      <span class="text-xl">💡</span>
                      Важно знать
                  </h4>
                  <p class="text-sm text-yellow-800 leading-relaxed">
                      Приложение автоматически суммирует время "снизу вверх". Если вы добавили 2 часа в подзадачу, они автоматически приплюсуются к родительской задаче в её графе "Факт".
                  </p>
              </div>
          </div>
        </section>

        <!-- 4. Сценарий: Добавление времени (Форма) -->
        <section class="space-y-8">
           <div class="flex items-end justify-between border-b pb-4">
               <h2 class="text-3xl font-bold text-gray-900 dark:text-gray-100">4. Форма добавления времени</h2>
          </div>

           <div class="flex flex-col lg:flex-row gap-12">
               <!-- Left: Explanation -->
               <div class="flex-1 space-y-6">
                   <p class="text-lg text-gray-700">
                       После нажатия на кнопку <strong>"+ Отразить"</strong> справа выезжает панель. Это ваш основной инструмент для превращения работы в данные.
                   </p>
                   
                   <div class="space-y-4">
                       <div class="flex items-start gap-4">
                           <div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-600 mt-1">1</div>
                           <div>
                               <h4 class="font-bold text-gray-900">Описание (Обязательно)</h4>
                               <p class="text-sm text-gray-600">
                                   Пишите подробно. Вместо "Работа" пишите "Верстка компонента Header". Это поможет при формировании актов для клиента.
                               </p>
                           </div>
                       </div>

                       <div class="flex items-start gap-4">
                           <div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-600 mt-1">2</div>
                           <div>
                               <h4 class="font-bold text-gray-900">Часы и Дата</h4>
                               <p class="text-sm text-gray-600">
                                   Укажите затраченное время в часах (например, 1.5). Дату можно выбрать, если вносите время за вчера.
                               </p>
                           </div>
                       </div>
                       
                        <div class="flex items-start gap-4">
                           <div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-600 mt-1">3</div>
                           <div>
                               <h4 class="font-bold text-gray-900">Учитывать в отчете (Checkbox)</h4>
                               <p class="text-sm text-gray-600">
                                   Галочка <strong>"Учитывать"</strong> означает, что это оплачиваемое (или полезное) время. Если галочку снять, время сохранится, но не пойдет в финансовые отчеты.
                               </p>
                           </div>
                       </div>
                   </div>
               </div>

               <!-- Right: Mockup -->
               <div class="w-full lg:w-[400px]">
                  <div class="border rounded-xl shadow-2xl bg-white overflow-hidden transform rotate-1 hover:rotate-0 transition-transform duration-500">
                      <div class="p-4 border-b bg-slate-50 flex justify-between items-center bg-gradient-to-r from-blue-50 to-indigo-50">
                          <h3 class="font-bold text-slate-800">Новая запись #123</h3>
                          <span class="text-slate-400 cursor-pointer hover:text-red-500">✕</span>
                      </div>
                      <div class="p-6 space-y-6">
                          <div>
                              <label class="text-xs font-bold text-slate-500 uppercase tracking-wide">Описание работы</label>
                              <textarea class="w-full border-2 border-slate-200 focus:border-blue-500 rounded-lg p-3 text-sm mt-2 outline-none transition-colors" rows="3" placeholder="Что вы сделали?">Разработка компонента списка задач</textarea>
                          </div>
                          <div class="flex gap-4">
                              <div class="w-1/2">
                                  <label class="text-xs font-bold text-slate-500 uppercase tracking-wide">Часы</label>
                                  <input type="number" class="w-full border-2 border-slate-200 focus:border-blue-500 rounded-lg p-3 text-sm mt-2 text-center font-bold text-lg outline-none" value="2.0">
                              </div>
                              <div class="w-1/2">
                                   <label class="text-xs font-bold text-slate-500 uppercase tracking-wide">Дата</label>
                                   <input type="date" class="w-full border-2 border-slate-200 focus:border-blue-500 rounded-lg p-3 text-sm mt-2 outline-none">
                              </div>
                          </div>
                          <div class="bg-slate-50 p-4 rounded-lg border border-slate-100 flex items-center gap-3">
                              <div class="relative flex items-center">
                                <input type="checkbox" checked class="w-5 h-5 text-blue-600 rounded border-gray-300 focus:ring-blue-500">
                              </div>
                              <label class="text-sm font-medium text-slate-700 select-none">Учитывать в отчете</label>
                          </div>
                          <div class="pt-2">
                              <button class="w-full py-3 bg-blue-600 text-white rounded-lg font-bold text-sm hover:bg-blue-700 shadow-lg shadow-blue-200 transition-all active:scale-95">Сохранить запись</button>
                          </div>
                      </div>
                  </div>
               </div>
           </div>
        </section>

        <!-- 5. Продвинутые функции: Split -->
        <section class="space-y-8">
          <div class="flex items-end justify-between border-b pb-4">
               <h2 class="text-3xl font-bold text-gray-900 dark:text-gray-100">5. Разделение времени (Split)</h2>
               <span class="text-sm text-gray-500 uppercase tracking-wider font-medium">Для профи</span>
          </div>
          
          <div class="bg-orange-50 border-l-4 border-orange-400 p-6 rounded-r-xl">
              <h3 class="font-bold text-orange-900 text-lg mb-2">Зачем это нужно?</h3>
              <p class="text-orange-800">
                  Представьте: вы работали 5 часов. Из них 3 часа — это полезная работа по задаче, а 2 часа — это внутренние обсуждения, которые клиент не оплачивает.
                  Вместо того чтобы удалять и создавать две разные записи, используйте <strong>Split</strong>.
              </p>
          </div>

          <div class="grid md:grid-cols-2 gap-12 items-start">
             <!-- Mockup: Split -->
             <div class="border rounded-xl shadow-xl bg-white overflow-hidden w-full">
                  <div class="p-4 bg-orange-50 border-b border-orange-100">
                      <h3 class="font-bold text-orange-800 flex items-center gap-2">
                           <span>✂️</span> Разделение (Split)
                      </h3>
                  </div>
                  <div class="p-6 space-y-6">
                       <div class="text-sm text-slate-600 bg-slate-50 p-3 rounded border">
                          Текущая запись: <strong>5:00</strong>
                       </div>
                       
                       <div>
                           <label class="text-xs font-bold text-slate-500 uppercase">Сколько отделить?</label>
                           <div class="flex gap-2 mt-2">
                               <input type="text" class="w-24 border-2 border-orange-200 focus:border-orange-500 rounded-lg p-2 text-center font-bold" value="2.0">
                               <button class="flex-1 bg-orange-500 text-white rounded-lg font-semibold text-sm hover:bg-orange-600 shadow-md">Разделить</button>
                           </div>
                       </div>
                       
                       <div class="flex items-center gap-2">
                          <input type="checkbox" class="w-4 h-4 text-orange-500 rounded border-gray-300">
                          <label class="text-sm text-slate-600">Учитывать новую запись?</label>
                      </div>
                  </div>
              </div>

              <!-- Steps -->
              <div class="space-y-6">
                <ol class="list-decimal list-inside space-y-4 text-gray-700 text-lg">
                    <li>Откройте существующую запись кликом по ней в дереве.</li>
                    <li>Прокрутите форму вниз до оранжевого блока <strong>Split</strong>.</li>
                    <li>Введите количество часов, которое нужно "откусить" от текущей записи.</li>
                    <li>Нажмите "Разделить".</li>
                </ol>
                <p class="text-sm text-gray-500 p-4 bg-gray-50 rounded-lg border">
                    <strong>Результат:</strong> Исходная запись уменьшится (было 5, станет 3). Появится новая запись на 2 часа. Сумма останется прежней.
                </p>
              </div>
          </div>
        </section>

        
        <!-- Footer Info -->
        <div class="text-center text-gray-400 text-sm py-12 border-t mt-12">
            <p>Версия Юзергайда: 2.0 (Massive Edition)</p>
            <p>Приложение "Учет часов и финансов" для Битрикс24.</p>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* Дополнительные стили для красоты текста */
.lead {
    line-height: 1.6;
}
</style>
