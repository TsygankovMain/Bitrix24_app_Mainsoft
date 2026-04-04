<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()

const quickStartSteps = [
  {
    title: 'Откройте приложение из Битрикс24',
    text: 'Главное меню приложения содержит отчеты, настройки и ссылку на это руководство.'
  },
  {
    title: 'Проверьте настройки при первом запуске',
    text: 'Если приложение только что установлено, откройте "Настройки -> Настройка полей (Маппинг)", выберите смарт-процесс и сохраните конфигурацию.'
  },
  {
    title: 'Фиксируйте время прямо в задаче',
    text: 'Во вкладке приложения в карточке задачи можно добавить, изменить, разделить или удалить запись времени.'
  },
  {
    title: 'Формируйте отчеты вручную',
    text: 'В отчетах сначала выберите период и фильтры, затем нажмите "Сформировать".'
  },
  {
    title: 'Выгружайте данные в Excel',
    text: 'Большинство отчетов и страница сырых данных поддерживают выгрузку в Excel для дальнейшей обработки.'
  }
]

const taskActions = [
  {
    title: 'Добавление записи',
    text: 'Нажмите "Отразить" у нужной задачи, заполните описание, часы, дату и сохраните запись.'
  },
  {
    title: 'Учитываемые и неучитываемые часы',
    text: 'Если запись отмечена как учитываемая, она попадает в основные финансовые и управленческие показатели. Неучитываемые часы остаются в истории, но считаются отдельно.'
  },
  {
    title: 'Редактирование',
    text: 'Любую существующую запись можно открыть повторно и изменить без перехода в другой раздел.'
  },
  {
    title: 'Разделение записи',
    text: 'Если одну запись нужно разбить на две части, используйте функцию разделения. Это удобно, когда часть времени должна учитываться, а часть нет.'
  },
  {
    title: 'Удаление',
    text: 'Удаление доступно из формы записи. Перед удалением приложение запрашивает подтверждение.'
  },
  {
    title: 'Стоимость часа',
    text: 'В задаче отображается ставка часа из настроек. Она используется для расчета суммы по учитываемым часам.'
  }
]

const reports = [
  {
    title: 'Отчет по сотрудникам',
    text: 'Показывает, как распределились часы по сотрудникам, проектам, задачам и отдельным меткам времени.'
  },
  {
    title: 'Отчет по проектам',
    text: 'Нужен для оценки загрузки и затрат в разрезе проектов и исполнителей.'
  },
  {
    title: 'Ежедневная нагрузка',
    text: 'Матрица по дням помогает быстро увидеть загруженность сотрудников и отклонения по дням.'
  },
  {
    title: 'Учет по проектам и задачам',
    text: 'Самый детальный отчет для разбора структуры проекта до уровня задач, сотрудников и отдельных записей.'
  },
  {
    title: 'Потери выручки',
    text: 'Показывает, где накапливаются неучтенные часы и какие проекты или связки сотрудников требуют внимания.'
  },
  {
    title: 'Дисциплина внесения времени',
    text: 'Помогает понять, насколько оперативно сотрудники вносят время в систему.'
  },
  {
    title: 'Фокус и распыление',
    text: 'Показывает, насколько концентрированно команда работает по проектам и где начинается распыление.'
  }
]

const filterRules = [
  'Период можно задать вручную или через быстрые пресеты: текущая неделя, предыдущая неделя, текущий месяц и предыдущий месяц.',
  'Фильтры по сотрудникам и проектам работают независимо от построения отчета: сначала настройка, затем кнопка "Сформировать".',
  'В фильтрах сотрудников и проектов есть два режима: обычный выбор и режим "Кроме", когда удобнее исключить несколько значений из общей выборки.',
  'Если в отчете уже есть данные, изменение фильтров само по себе не перестраивает отчет, пока вы снова не нажмете "Сформировать".',
  'Кнопка "Скачать Excel" выгружает текущую выборку отчета.'
]

const settingsSections = [
  {
    title: 'Настройка полей (Маппинг)',
    text: 'Основной экран первичной настройки. Здесь выбирается смарт-процесс, создаются поля, задается ставка часа и сохраняется маппинг.'
  },
  {
    title: 'Сырые данные (БД)',
    text: 'Технический раздел для просмотра локально сохраненных записей, ручной синхронизации с Битрикс24 и динамической выгрузки данных в Excel.'
  },
  {
    title: 'Кликабельные метки',
    text: 'В настройках можно включить ссылки на карточки элементов Битрикс24 прямо из детализированных отчетов.'
  },
  {
    title: 'Панель отладки',
    text: 'Раздел для диагностики запросов и системных событий. Обычно нужен администраторам и разработчикам.'
  }
]

const faqItems = [
  {
    title: 'Отчет пустой',
    text: 'Проверьте период, сотрудников и проекты в фильтрах, затем нажмите "Сформировать". Если приложение только настроено, убедитесь, что в системе уже есть записи времени.'
  },
  {
    title: 'Не вижу нужный смарт-процесс или поля',
    text: 'Откройте раздел маппинга, подгрузите список процессов и при необходимости создайте смарт-процесс и поля прямо из приложения.'
  },
  {
    title: 'Вкладка в задаче не работает',
    text: 'Приложение должно открываться внутри карточки задачи Битрикс24. Если открывать встроенную страницу напрямую, часть функций будет недоступна.'
  },
  {
    title: 'Excel нужен не по отчету, а по исходным данным',
    text: 'Используйте раздел "Сырые данные (БД)". Там можно выбрать тип даты, период и набор полей для выгрузки.'
  }
]
</script>

<template>
  <div class="min-h-screen bg-white px-4 py-6 sm:px-8">
    <div class="mx-auto max-w-6xl space-y-10">
      <section class="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50 px-6 py-8 shadow-sm">
        <B24Button label="Назад к меню" color="link" @click="router.push('/')" class="mb-4 pl-0" />

        <div class="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <div class="flex items-start gap-4">
            <div class="rounded-2xl bg-blue-100 p-4 text-blue-700">
              <BookOpen1Icon class="h-8 w-8" />
            </div>
            <div class="space-y-3">
              <div>
                <h1 class="text-3xl font-bold text-slate-900 sm:text-4xl">Руководство пользователя</h1>
                <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-600 sm:text-base">
                  Это краткий и актуальный справочник по основным сценариям работы с приложением:
                  фиксация времени в задачах, формирование отчетов, выгрузка Excel и настройка данных.
                </p>
              </div>

              <div class="grid gap-3 sm:grid-cols-3">
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-wide text-slate-500">Основной сценарий</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">Учесть время в задаче</div>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-wide text-slate-500">Аналитика</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">7 отчетов и Excel</div>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-wide text-slate-500">Администрирование</div>
                  <div class="mt-1 text-sm font-medium text-slate-900">Маппинг, сырые данные, отладка</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="space-y-5">
        <div>
          <h2 class="text-2xl font-bold text-slate-900">Быстрый старт</h2>
          <p class="mt-2 text-sm text-slate-600">
            Если вы открыли приложение впервые, достаточно пройти эти шаги.
          </p>
        </div>

        <div class="grid gap-4 lg:grid-cols-5">
          <div
            v-for="(step, index) in quickStartSteps"
            :key="step.title"
            class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div class="mb-4 flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
              {{ index + 1 }}
            </div>
            <h3 class="text-base font-semibold text-slate-900">{{ step.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-slate-600">{{ step.text }}</p>
          </div>
        </div>
      </section>

      <section class="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div class="mb-5">
            <h2 class="text-2xl font-bold text-slate-900">Работа внутри задачи</h2>
            <p class="mt-2 text-sm text-slate-600">
              Основной рабочий сценарий начинается во вкладке приложения в карточке задачи Битрикс24.
            </p>
          </div>

          <div class="space-y-4">
            <div
              v-for="item in taskActions"
              :key="item.title"
              class="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4"
            >
              <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-900">{{ item.title }}</h3>
              <p class="mt-2 text-sm leading-6 text-slate-600">{{ item.text }}</p>
            </div>
          </div>
        </div>

        <div class="rounded-3xl border border-blue-200 bg-blue-50 p-6 shadow-sm">
          <h2 class="text-2xl font-bold text-slate-900">Что важно помнить</h2>
          <div class="mt-5 space-y-4 text-sm leading-6 text-slate-700">
            <p>
              Записи времени вносятся в связанный смарт-процесс Битрикс24 и потом используются в отчетах приложения.
            </p>
            <p>
              Отчетность опирается на период, сотрудников и проекты, поэтому при разборе данных в первую очередь проверяйте фильтры.
            </p>
            <p>
              Учитываемые и неучитываемые часы всегда разделяются в аналитике, поэтому статус записи влияет на итоговые показатели.
            </p>
            <p>
              Встроенная справка и настройки доступны без выхода из приложения, поэтому базовые вопросы обычно решаются внутри интерфейса.
            </p>
          </div>
        </div>
      </section>

      <section class="space-y-5">
        <div>
          <h2 class="text-2xl font-bold text-slate-900">Отчеты</h2>
          <p class="mt-2 text-sm text-slate-600">
            В приложении доступны как базовые управленческие отчеты, так и более аналитические экраны для контроля качества учета.
          </p>
        </div>

        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div
            v-for="report in reports"
            :key="report.title"
            class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <h3 class="text-lg font-semibold text-slate-900">{{ report.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-slate-600">{{ report.text }}</p>
          </div>
        </div>
      </section>

      <section class="rounded-3xl border border-slate-200 bg-slate-50 p-6 shadow-sm">
        <div class="max-w-3xl">
          <h2 class="text-2xl font-bold text-slate-900">Как работают фильтры и формирование отчетов</h2>
          <p class="mt-2 text-sm text-slate-600">
            Это одна из самых важных частей интерфейса, потому что все отчеты теперь строятся по одинаковой логике.
          </p>
        </div>

        <div class="mt-6 grid gap-4 md:grid-cols-2">
          <div
            v-for="rule in filterRules"
            :key="rule"
            class="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-sm leading-6 text-slate-600"
          >
            {{ rule }}
          </div>
        </div>
      </section>

      <section class="space-y-5">
        <div>
          <h2 class="text-2xl font-bold text-slate-900">Настройки и администрирование</h2>
          <p class="mt-2 text-sm text-slate-600">
            Эти разделы обычно нужны при первом запуске, изменении конфигурации или диагностике данных.
          </p>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <div
            v-for="section in settingsSections"
            :key="section.title"
            class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <h3 class="text-lg font-semibold text-slate-900">{{ section.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-slate-600">{{ section.text }}</p>
          </div>
        </div>
      </section>

      <section class="space-y-5 pb-8">
        <div>
          <h2 class="text-2xl font-bold text-slate-900">Частые вопросы</h2>
          <p class="mt-2 text-sm text-slate-600">
            Короткие ответы на типовые вопросы пользователей и администраторов.
          </p>
        </div>

        <div class="space-y-4">
          <div
            v-for="item in faqItems"
            :key="item.title"
            class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <h3 class="text-base font-semibold text-slate-900">{{ item.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-slate-600">{{ item.text }}</p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
