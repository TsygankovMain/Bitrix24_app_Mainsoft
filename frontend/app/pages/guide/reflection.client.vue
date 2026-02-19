<script setup lang="ts">

useHead({
  title: 'Инструкция: Учёт времени'
})

const router = useRouter()
const route = useRoute()

const backLabel = computed(() => {
  return route.query.from === 'embedded' ? 'Назад к задаче' : 'Назад к меню'
})

function goBack() {
  if (route.query.from === 'embedded') {
    router.back()
  } else {
    router.push('/guide')
  }
}
</script>

<template>
  <div class="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-screen w-full flex-1 min-w-0">
    <div class="max-w-4xl mx-auto w-full">
      <!-- Header -->
      <div class="mb-8">
        <B24Button 
          :label="backLabel" 
          color="link" 
          @click="goBack" 
          class="mb-4 pl-0" 
        />
        <h1 class="text-3xl font-bold text-gray-900 dark:text-gray-100">
          Как отражать часы в задаче
        </h1>
        <p class="mt-2 text-lg text-gray-600 dark:text-gray-400">
          Полное руководство по работе с вкладкой «Учёт часов».
        </p>
      </div>

      <div class="space-y-12">

        <!-- 1. Интерфейс -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100">1. Интерфейс вкладки</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Вкладка <strong>«Учёт часов»</strong> находится внутри каждой задачи. Она показывает структуру подзадач и позволяет вносить время.
          </p>
          
          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <!-- Placeholder for Screenshot 1 -->
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Сюда нужно вставить скриншот общего вида вкладки</p>
             <p class="text-sm text-gray-400 mt-2">Стрелками указать: 1. Дерево задач, 2. Кнопку "Отразить", 3. Итоговые суммы</p>
          </div>

          <ul class="list-disc list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li><strong>Дерево задач:</strong> Показывает текущую задачу и все её подзадачи.</li>
            <li><strong>Часы (Факт / План):</strong> Справа от каждой задачи видно, сколько времени уже внесено.</li>
            <li><strong>Итоги:</strong> В самом низу — суммарное время по всему дереву.</li>
          </ul>
        </section>

        <!-- 2. Добавление записи -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100">2. Как внести время</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Чтобы добавить запись о работе:
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите кнопку <strong>«Отразить»</strong> (синий плюс) напротив нужной задачи.</li>
            <li>Откроется форма добавления записи.</li>
            <li>Заполните поля:
                <ul class="list-disc list-inside ml-6 mt-1 text-gray-600">
                    <li><strong>Описание:</strong> Что именно было сделано.</li>
                    <li><strong>Часы:</strong> Затраченное время.</li>
                    <li><strong>Учитывать:</strong> Галочка (влияет на зарплату/отчеты).</li>
                </ul>
            </li>
            <li>Нажмите <strong>«Сохранить»</strong>.</li>
          </ol>

          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <!-- Placeholder for Screenshot 2 -->
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Скриншот формы добавления</p>
             <p class="text-sm text-gray-400 mt-2">Стрелкой указать на кнопку "Сохранить"</p>
          </div>
        </section>

        <!-- 3. Разделение записи -->
        <section class="space-y-4">
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100">3. Разделение записи (Split)</h2>
          <p class="text-gray-700 dark:text-gray-300">
            Если нужно разделить одну запись на две (например, часть времени оплачивается, а часть нет):
          </p>
          <ol class="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300 ml-4">
            <li>Нажмите на существующую запись в списке.</li>
            <li>Внизу формы найдите блок <strong>«Разделение (Split)»</strong>.</li>
            <li>Введите количество часов для отделения.</li>
            <li>Выберите, учитывать ли отделяемые часы (галочка «Учитывать?»).</li>
            <li>Нажмите <strong>«Разделить»</strong>.</li>
          </ol>

          <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 bg-gray-50 flex flex-col items-center justify-center text-center">
             <!-- Placeholder for Screenshot 3 -->
             <div class="mb-4 text-4xl">📸</div>
             <p class="font-medium text-gray-500">Скриншот блока Split</p>
             <p class="text-sm text-gray-400 mt-2">Стрелками показать поле ввода часов и кнопку "Разделить"</p>
          </div>
          
          <div class="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r">
            <p class="text-blue-700">
              <strong>Обратите внимание:</strong> При разделении старая запись уменьшается на указанное количество часов, и создается новая запись с этим количеством. Общая сумма часов не меняется.
            </p>
          </div>
        </section>

      </div>
      
      <div class="mt-12 pt-8 border-t text-center">
        <B24Button label="Вернуться в задачу" size="lg" @click="router.back()" />
      </div>

    </div>
  </div>
</template>
