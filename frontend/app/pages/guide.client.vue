<script setup lang="ts">
import { BookOpen1Icon } from '@bitrix24/b24icons-vue/main'

useHead({
  title: 'Юзергайд'
})

const router = useRouter()

const workspaceCards = [
  {
    title: 'Задачи',
    text: 'Здесь фиксируется время, редактируются записи и при необходимости выполняется выгрузка в Bitrix24.'
  },
  {
    title: 'Проекты',
    text: 'Здесь открывается карточка проекта, настраиваются куратор, компания, юрлицо и проверяются сигналы по списаниям.'
  },
  {
    title: 'Отчеты',
    text: 'Здесь выбирается период, фильтры и только после этого формируется нужная аналитика.'
  }
]

const faqItems = [
  {
    title: 'Почему отчет пустой?',
    text: 'Обычно причина в периоде или фильтрах. Сначала выберите диапазон дат и нужные отборы, затем нажмите «Сформировать».'
  },
  {
    title: 'Где искать проект?',
    text: 'Из новой главной можно открыть карточку проекта справа или перейти сразу в сам проект Bitrix24 по кнопке «Открыть проект».'
  },
  {
    title: 'Как искать компанию?',
    text: 'В проектах и фильтрах работает поиск и по названию, и по ИНН. Это особенно удобно для длинных справочников.'
  },
  {
    title: 'Когда нужен раздел «Проверка данных»?',
    text: 'Когда нужно проверить исходные записи, выполнить техническую выгрузку или разобраться, почему цифры отличаются от ожиданий.'
  }
]
</script>

<template>
  <div class="ms-page-shell">
    <div class="ms-page-frame space-y-8">
      <section class="ms-surface-hero px-6 py-7">
        <B24Button label="Назад к меню" color="link" @click="router.push('/')" class="mb-4 pl-0" />

        <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
          <div class="min-w-0">
            <div class="flex items-start gap-4">
              <div class="rounded-2xl bg-lime-100 p-4 text-lime-700">
                <BookOpen1Icon class="h-8 w-8" />
              </div>

              <div class="min-w-0 flex-1 space-y-3">
                <div class="ms-eyebrow">Guide</div>
                <div>
                  <h1 class="ms-title">Как работать с приложением</h1>
                  <p class="mt-3 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
                    Этот гайд показывает только основные рабочие сценарии: где фиксировать время, как открыть и вести проект,
                    и как быстро собрать нужный отчет без лишних действий.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="grid content-start gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <div class="ms-stat-card">
              <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Шаг 1</div>
              <div class="mt-2 text-sm font-semibold text-slate-900">Фиксируйте время внутри задачи</div>
            </div>
            <div class="ms-stat-card">
              <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Шаг 2</div>
              <div class="mt-2 text-sm font-semibold text-slate-900">Открывайте проект из карточки или главной</div>
            </div>
            <div class="ms-stat-card">
              <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Шаг 3</div>
              <div class="mt-2 text-sm font-semibold text-slate-900">Собирайте отчет по кнопке «Сформировать»</div>
            </div>
          </div>
        </div>
      </section>

      <section class="grid gap-4 lg:grid-cols-3">
        <article
          v-for="card in workspaceCards"
          :key="card.title"
          class="ms-panel"
        >
          <div class="ms-eyebrow">{{ card.title }}</div>
          <p class="mt-4 text-sm leading-6 text-slate-600">
            {{ card.text }}
          </p>
        </article>
      </section>

      <section class="ms-surface p-6">
        <div class="mb-5">
          <h2 class="text-2xl font-semibold text-slate-900">1. Как фиксировать время в задаче</h2>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            Это основной пользовательский сценарий. Вся дальнейшая аналитика строится на этих записях.
          </p>
        </div>

        <div class="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(320px,1.05fr)] xl:items-start">
          <div class="space-y-3">
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Откройте вкладку приложения внутри задачи</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                В задаче отображается дерево подзадач и уже сохраненные записи времени.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Нажмите на нужную запись или создайте новую</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                В форме задаются сотрудник, часы, дата и описание. При необходимости запись можно исправить позже.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Отметьте, учитывать ли часы</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Учитываемые часы попадают в основную аналитику. Неучитываемые остаются в истории, но считаются отдельно.
              </p>
            </div>
          </div>

          <div class="guide-mockup">
            <div class="guide-window">
              <div class="guide-window-bar">
                <span>Отражение часов</span>
                <span class="guide-dot-row">
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                </span>
              </div>

              <div class="guide-window-body space-y-3">
                <div class="guide-line-item">
                  <div>
                    <div class="guide-line-title">Интеграция с CRM</div>
                    <div class="guide-line-meta">Подзадача · Анна Петрова</div>
                  </div>
                  <div class="text-right">
                    <div class="guide-hours guide-hours-positive">6.50 ч</div>
                    <div class="guide-line-meta">учтено</div>
                  </div>
                </div>

                <div class="guide-card-soft">
                  <div class="guide-form-grid">
                    <div class="guide-field">
                      <div class="guide-field-label">Сотрудник</div>
                      <div class="guide-field-input">Анна Петрова</div>
                    </div>
                    <div class="guide-field">
                      <div class="guide-field-label">Часы</div>
                      <div class="guide-field-input">6.5</div>
                    </div>
                  </div>

                  <div class="guide-form-grid">
                    <div class="guide-field">
                      <div class="guide-field-label">Дата</div>
                      <div class="guide-field-input">05.04.2026</div>
                    </div>
                    <div class="guide-toggle">
                      <span>Учитывать</span>
                      <span class="guide-switch guide-switch-active" />
                    </div>
                  </div>

                  <div class="guide-field">
                    <div class="guide-field-label">Описание</div>
                    <div class="guide-field-textarea">Подготовка оценки и сверка трудозатрат по проекту.</div>
                  </div>
                </div>

                <div class="flex flex-wrap gap-2">
                  <span class="guide-pill guide-pill-lime">Сохранить</span>
                  <span class="guide-pill guide-pill-default">В отчет Bitrix24</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="ms-surface p-6">
        <div class="mb-5">
          <h2 class="text-2xl font-semibold text-slate-900">2. Как работать с проектом</h2>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            Проект можно открыть с новой главной или из раздела управления проектами. Карточка открывается справа, сам проект Bitrix24 открывается отдельной кнопкой.
          </p>
        </div>

        <div class="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(320px,1.05fr)] xl:items-start">
          <div class="space-y-3">
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Откройте карточку проекта</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Справа откроется слайдер с локальными полями проекта: куратор, компания, наше юрлицо, даты, ставка и бюджет.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Используйте поиск по справочникам</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                В компаниях и юрлицах поиск работает и по названию, и по ИНН. Это помогает быстро найти нужную запись в длинном списке.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Нажмите «Открыть проект»</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Кнопка переводит в сам проект Bitrix24 по его рабочей ссылке, а не в отдельный внутренний отчет.
              </p>
            </div>
          </div>

          <div class="guide-mockup">
            <div class="guide-window">
              <div class="guide-window-bar">
                <span>Карточка проекта</span>
                <span class="guide-dot-row">
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                </span>
              </div>

              <div class="guide-window-body space-y-3">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <div class="guide-line-title">Внедрение ERP для ACME</div>
                    <div class="guide-line-meta">В работе · нет списаний 12 дней</div>
                  </div>
                  <span class="guide-pill guide-pill-default">Delivery</span>
                </div>

                <div class="guide-card-soft space-y-3">
                  <div class="guide-field">
                    <div class="guide-field-label">Куратор</div>
                    <div class="guide-search-input">Иван Соколов</div>
                  </div>
                  <div class="guide-field">
                    <div class="guide-field-label">Компания</div>
                    <div class="guide-search-input">ACME Group · ИНН 7704123456</div>
                  </div>
                  <div class="guide-field">
                    <div class="guide-field-label">Наше юрлицо</div>
                    <div class="guide-search-input">ООО «Мейнсофт» · ИНН 7704987654</div>
                  </div>
                </div>

                <div class="flex flex-wrap gap-2">
                  <span class="guide-pill guide-pill-lime">Сохранить</span>
                  <span class="guide-pill guide-pill-default">Открыть проект</span>
                  <span class="guide-pill guide-pill-ghost">В архив</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="ms-surface p-6">
        <div class="mb-5">
          <h2 class="text-2xl font-semibold text-slate-900">3. Как собрать отчет</h2>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            Все отчеты работают по одной схеме: сначала период и фильтры, потом формирование, после этого при необходимости выгрузка в Excel.
          </p>
        </div>

        <div class="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(320px,1.05fr)] xl:items-start">
          <div class="space-y-3">
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Выберите период</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Можно задать даты вручную или выбрать готовый пресет: неделя, прошлый месяц и другие быстрые интервалы.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Настройте фильтры</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Сотрудников, проекты и юрлица можно выбирать напрямую или использовать режим исключения, если удобнее убрать несколько значений из выборки.
              </p>
            </div>
            <div class="ms-panel-muted">
              <div class="text-sm font-semibold text-slate-900">Нажмите «Сформировать»</div>
              <p class="mt-2 text-sm leading-6 text-slate-600">
                Отчет строится только по кнопке. Если данные подходят, их можно сразу выгрузить в Excel.
              </p>
            </div>
          </div>

          <div class="guide-mockup">
            <div class="guide-window">
              <div class="guide-window-bar">
                <span>Отчет по проектам</span>
                <span class="guide-dot-row">
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                  <span class="guide-dot" />
                </span>
              </div>

              <div class="guide-window-body space-y-3">
                <div class="guide-filter-grid">
                  <div class="guide-field">
                    <div class="guide-field-label">Период</div>
                    <div class="guide-field-input">01.03.2026 - 31.03.2026</div>
                  </div>
                  <div class="guide-field">
                    <div class="guide-field-label">Проект</div>
                    <div class="guide-search-input">ACME Group</div>
                  </div>
                </div>

                <div class="flex flex-wrap gap-2">
                  <span class="guide-pill guide-pill-ghost">Эта неделя</span>
                  <span class="guide-pill guide-pill-ghost">Этот месяц</span>
                  <span class="guide-pill guide-pill-ghost">Кроме</span>
                </div>

                <div class="guide-card-soft">
                  <div class="guide-line-item !border-none !bg-transparent !p-0">
                    <div>
                      <div class="guide-line-title">ACME Group</div>
                      <div class="guide-line-meta">Иван Соколов · 146.5 ч</div>
                    </div>
                    <div class="text-right">
                      <div class="guide-hours guide-hours-positive">439 500 ₽</div>
                      <div class="guide-line-meta">учтено</div>
                    </div>
                  </div>
                </div>

                <div class="flex flex-wrap gap-2">
                  <span class="guide-pill guide-pill-lime">Сформировать</span>
                  <span class="guide-pill guide-pill-default">Скачать Excel</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="grid gap-4 lg:grid-cols-2">
        <article
          v-for="item in faqItems"
          :key="item.title"
          class="ms-panel"
        >
          <h3 class="text-base font-semibold text-slate-900">{{ item.title }}</h3>
          <p class="mt-2 text-sm leading-6 text-slate-600">{{ item.text }}</p>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.guide-mockup {
  border: 1px solid rgba(216, 226, 238, 0.95);
  border-radius: 26px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
  padding: 14px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
}

.guide-window {
  overflow: hidden;
  border: 1px solid rgba(216, 226, 238, 0.95);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
}

.guide-window-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.9);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(241, 245, 249, 0.92));
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.guide-window-body {
  padding: 16px;
}

.guide-dot-row {
  display: inline-flex;
  gap: 6px;
}

.guide-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #cbd5e1;
}

.guide-card-soft {
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 18px;
  background: #f8fafc;
  padding: 14px;
}

.guide-line-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 18px;
  background: #fff;
  padding: 14px;
}

.guide-line-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.guide-line-meta {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.guide-hours {
  font-size: 14px;
  font-weight: 700;
}

.guide-hours-positive {
  color: #0f766e;
}

.guide-form-grid,
.guide-filter-grid {
  display: grid;
  gap: 12px;
}

.guide-form-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.guide-filter-grid {
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
}

.guide-field {
  display: grid;
  gap: 6px;
}

.guide-field-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.guide-field-input,
.guide-search-input,
.guide-field-textarea {
  border: 1px solid rgba(216, 226, 238, 0.95);
  border-radius: 14px;
  background: #fff;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.5;
}

.guide-field-input,
.guide-search-input {
  padding: 10px 12px;
}

.guide-search-input::before {
  content: '';
}

.guide-field-textarea {
  min-height: 72px;
  padding: 10px 12px;
}

.guide-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(216, 226, 238, 0.95);
  border-radius: 14px;
  background: #fff;
  padding: 10px 12px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
}

.guide-switch {
  position: relative;
  width: 36px;
  height: 20px;
  border-radius: 999px;
  background: #cbd5e1;
}

.guide-switch::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: white;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
}

.guide-switch-active {
  background: #b7ea2c;
}

.guide-switch-active::after {
  left: 18px;
}

.guide-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 700;
}

.guide-pill-lime {
  background: #b7ea2c;
  color: #0f172a;
}

.guide-pill-default {
  background: #e2e8f0;
  color: #334155;
}

.guide-pill-ghost {
  border: 1px solid rgba(216, 226, 238, 0.95);
  background: #fff;
  color: #64748b;
}

@media (max-width: 640px) {
  .guide-form-grid,
  .guide-filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
