<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()

const fields = [
  { key: 'id_zadachi', label: 'ID Задачи', type: 'integer', desc: 'ID задачи, к которой относится запись времени.' },
  { key: 'sotrudnik', label: 'Сотрудник', type: 'employee', desc: 'Пользователь Битрикс24, ответственный за списание времени.' },
  { key: 'kolichestvo_chasov', label: 'Количество часов', type: 'double', desc: 'Затраченное время (числовое значение).' },
  { key: 'uchitivaem', label: 'Учитываем?', type: 'boolean', desc: 'Флаг (Да/Нет), указывающий, является ли время оплачиваемым.' },
  { key: 'ne_uchitivaemie_chasi', label: 'Неучитываемые часы', type: 'double', desc: 'Часы, которые не идут в зачет.' },
  { key: 'opisanie', label: 'Описание', type: 'string', desc: 'Комментарий к списанию времени.' },
  { key: 'project_title', label: 'Название Проекта', type: 'string', desc: 'Название проекта или рабочей группы.' },
  { key: 'project_id', label: 'ID Проекта', type: 'integer', desc: 'Уникальный идентификатор проекта (группы).' },
  { key: 'data', label: 'Дата', type: 'date', desc: 'Дата, за которую внесено время.' },
  { key: 'id_zadach_ierarhiya', label: 'Иерархия ID', type: 'string (JSON)', desc: 'Полный путь ID задач от корневой до текущей.' },
  { key: 'title_zadach_ierarhiya', label: 'Иерархия Названий', type: 'string (JSON)', desc: 'Полный путь названий задач от корневой до текущей.' },
]
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
      </div>

      <div class="space-y-12">
        
        <!-- Section 1: Intro -->

        <section class="bg-purple-50 dark:bg-gray-800 p-6 rounded-lg border border-purple-100 dark:border-gray-700">
          <p class="text-lg text-gray-700 dark:text-gray-300 leading-relaxed">
            Данное приложение предназначено для учета и анализа рабочего времени сотрудников на основе данных из Смарт-процессов Битрикс24.
            Оно позволяет агрегировать данные от таймшетов, распределять их по проектам и строить детальные отчеты.
          </p>
        </section>

        <!-- Section 2: Configuration -->
        <section>
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-4 border-b pb-2">1. Настройка и Данные</h2>
          <div class="bg-blue-50 dark:bg-gray-800 p-6 rounded-lg mb-6">
            <h3 class="text-lg font-semibold text-blue-900 dark:text-blue-100 mb-2">Смарт-процесс и Маппинг</h3>
            <p class="text-gray-700 dark:text-gray-300 mb-4">
              Для работы приложения необходимо указать источник данных. Это делается в разделе 
              <span @click="router.push('/settings/mapping')" class="text-blue-600 cursor-pointer hover:underline font-medium">Настройки -> Маппинг</span>.
            </p>
            <p class="text-gray-700 dark:text-gray-300">
              Вам нужно выбрать Смарт-процесс, в котором хранятся записи о времени, и сопоставить поля приложения с полями этого процесса.
            </p>
          </div>

          <h4 class="text-md font-bold text-gray-800 dark:text-gray-200 mb-3">Описание внутренних полей приложения:</h4>
          <div class="overflow-x-auto border rounded-lg">
            <table class="min-w-full divide-y divide-gray-200 bg-white dark:bg-gray-800">
              <thead class="bg-gray-50 dark:bg-gray-700">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Поле (Key)</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Название</th>
                  <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Описание</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
                <tr v-for="field in fields" :key="field.key">
                    <td class="px-4 py-2 text-sm font-mono text-purple-600 bg-gray-50 dark:bg-gray-900">{{ field.key }}</td>
                    <td class="px-4 py-2 text-sm font-medium text-gray-900 dark:text-gray-100">{{ field.label }}</td>
                    <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">{{ field.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Section 3: Reports -->
        <section>
          <h2 class="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-4 border-b pb-2">2. Доступные Отчеты</h2>
          <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            
            <!-- Employee Report -->
            <div class="border rounded-xl p-6 hover:shadow-lg transition-shadow bg-white dark:bg-gray-800">
                <div class="flex items-center gap-3 mb-3">
                    <div class="w-3 h-3 rounded-full bg-blue-500"></div>
                    <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Отчет по сотрудникам</h3>
                </div>
                <p class="text-gray-600 dark:text-gray-400 mb-4">
                    Позволяет увидеть, над какими проектами работал конкретный сотрудник и сколько времени потратил.
                </p>
                <ul class="list-disc list-inside text-sm text-gray-500 mb-4 space-y-1">
                    <li>Фильтр по датам и проектам</li>
                    <li>Группировка: Сотрудник -> Проект -> Задача</li>
                    <li>Экспорт в Excel</li>
                </ul>
                <B24Button label="Перейти" size="sm" color="primary" variant="outline" @click="router.push('/reports/employee')" />
            </div>

            <!-- Project Report -->
            <div class="border rounded-xl p-6 hover:shadow-lg transition-shadow bg-white dark:bg-gray-800">
                <div class="flex items-center gap-3 mb-3">
                    <div class="w-3 h-3 rounded-full bg-indigo-500"></div>
                    <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Отчет по проектам</h3>
                </div>
                <p class="text-gray-600 dark:text-gray-400 mb-4">
                    Фокусируется на проектах. Показывает, кто из сотрудников участвовал в проекте и их вклад.
                </p>
                <ul class="list-disc list-inside text-sm text-gray-500 mb-4 space-y-1">
                    <li>Анализ рентабельности проекта</li>
                    <li>Группировка: Проект -> Сотрудник -> Задача</li>
                    <li>Экспорт в Excel</li>
                </ul>
                <B24Button label="Перейти" size="sm" color="primary" variant="outline" @click="router.push('/reports/project')" />
            </div>

            <!-- Daily Report -->
            <div class="border rounded-xl p-6 hover:shadow-lg transition-shadow bg-white dark:bg-gray-800">
                <div class="flex items-center gap-3 mb-3">
                    <div class="w-3 h-3 rounded-full bg-orange-500"></div>
                    <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Ежедневная нагрузка</h3>
                </div>
                <p class="text-gray-600 dark:text-gray-400 mb-4">
                    Матричный вид (Табель рабочего времени), отображающий активность сотрудников по дням месяца.
                    Идеально подходит для контроля заполнения таймшетов и выявления пропусков.
                </p>
                <B24Button label="Перейти" size="sm" color="primary" variant="outline" @click="router.push('/reports/daily')" />
            </div>
          </div>
        </section>

        <!-- Section 4: Sync -->
        <section class="bg-yellow-50 dark:bg-yellow-900/20 p-6 rounded-lg border border-yellow-100 dark:border-yellow-900">
            <h2 class="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">Важно: Обновление данных</h2>
            <p class="text-gray-700 dark:text-gray-300">
                Приложение использует локальную базу данных для быстрого построения отчетов. 
                Чтобы увидеть свежие записи из Битрикс24, необходимо нажимать кнопку 
                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800 mx-1 border border-gray-300">Обновить</span> 
                внутри любого отчета. Это запустит процесс синхронизации новых меток времени.
            </p>
        </section>

      </div>
    </div>
  </div>
</template>
