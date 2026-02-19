<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()
</script>

<template>
  <div class="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-screen">
    <div class="w-full">
      <!-- Header -->
      <div class="mb-8">
        <B24Button label="Назад к отчетам" color="link" @click="router.push('/')" class="mb-4 pl-0" />
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

      <div class="space-y-12 max-w-5xl">
        
        <!-- Section 1: Interface -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">1. Интерфейс вкладки «Учёт часов»</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Вкладка <strong>«Учёт часов»</strong> находится внутри каждой задачи. Она показывает структуру подзадач и позволяет вносить время.
          </p>
          
          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Скриншот общего вида вкладки</p>
             <p class="text-xs text-gray-400 mt-2">1. Дерево задач | 2. Кнопка "Отразить" | 3. Итоговые суммы</p>
          </div>

          <ul class="list-disc list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li><strong>Дерево задач:</strong> Показывает текущую задачу и все её подзадачи.</li>
            <li><strong>Часы (Факт / План):</strong> Справа от каждой задачи видно, сколько времени уже внесено.</li>
            <li><strong>Итоги:</strong> В самом низу — суммарное время по всему дереву.</li>
          </ul>
        </section>

        <!-- Section 2: Adding Time -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">2. Как внести время</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Чтобы добавить запись о работе:
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите кнопку <strong>«Отразить»</strong> (синий плюс) напротив нужной задачи.</li>
            <li>Откроется форма (справа).</li>
            <li>Заполните поля:
                <ul class="list-disc list-inside ml-6 mt-1 text-gray-600 dark:text-gray-400">
                    <li><strong>Описание:</strong> Что именно было сделано.</li>
                    <li><strong>Часы:</strong> Затраченное время.</li>
                    <li><strong>Учитывать:</strong> Галочка (влияет на отчеты).</li>
                </ul>
            </li>
            <li>Нажмите <strong>«Сохранить»</strong>.</li>
          </ol>

          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Скриншот формы добавления</p>
          </div>
        </section>

        <!-- Section 3: Splitting Time -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 border-b pb-2">3. Разделение записи (Split)</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Если нужно разделить одну запись на две (например, часть времени оплачивается, а часть нет):
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите на существующую запись в списке (дереве).</li>
            <li>В форме редактирования найдите блок <strong>«Разделение (Split)»</strong>.</li>
            <li>Введите количество часов для отделения.</li>
            <li>Выберите, учитывать ли отделяемые часы.</li>
            <li>Нажмите <strong>«Разделить»</strong>.</li>
          </ol>

          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Скриншот блока Split</p>
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
