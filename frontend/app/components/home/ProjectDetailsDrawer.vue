<script setup lang="ts">
/**
 * Боковая панель выбранного проекта на главной.
 *
 * До этой правки панель была обычным `<aside>` внутри сетки рядом с таблицей
 * проектов. Во фрейме портала ширины почти никогда не хватает на две колонки
 * (обычные 1000–1400 px против точки xl = 1280 px плюс поля страницы), колонка
 * переносилась вниз, и «нажал на проект — он открылся где-то внизу» стало
 * главной жалобой на экран. Панель переехала поверх содержимого: таблица
 * теперь всегда во всю ширину и не прыгает при выборе строки.
 *
 * Разметка — калька с frontend/app/components/projects/ProjectBoardDrawer.vue и
 * CreateProjectDrawer.vue: оверлей `fixed inset-0` с `justify-end`, внутри
 * `aside` фиксированной ширины, шапка / прокручиваемое тело / подвал. Это
 * единственная схема боковых панелей, проверенная в этом приложении в проде.
 *
 * Почему `fixed inset-0`, а не `absolute` от страницы и не `100vh`. У фрейма
 * нет своей прокрутки: высоту фрейма приложение просит у портала само
 * (`requestIframeAutoHeight` → `BX24.fitWindow`, см. layouts/default.vue), и
 * вьюпорт фрейма равен его содержимому. Значит `inset-0` внутри фрейма
 * накрывает ровно ту область, которую сотрудник видит как «приложение», а
 * `h-full` у панели — всю её высоту. `100vh` внутри фрейма — это высота
 * вьюпорта фрейма, а не окна портала, то есть в лучшем случае то же самое, но
 * без гарантии, что значение не устарело после очередного fitWindow.
 * Содержимое панели прокручивается внутри неё самой (`overflow-y-auto` у тела),
 * поэтому фрейму не приходится расти под открытую панель.
 *
 * На узком фрейме (меньше 900 px — портал на ноутбуке с раскрытым меню, окно в
 * половину экрана) панель занимает всю ширину: 460 px рядом с таблицей на
 * 800 px сломали бы и панель, и таблицу.
 *
 * Оверлей закрывает панель по клику мимо — в отличие от CreateProjectDrawer,
 * где этого просил не делать заказчик. Здесь панель ничего не редактирует,
 * терять при случайном клике нечего, а ProjectBoardDrawer ведёт себя так же.
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { getProjectStageClass, type ProjectPanel } from '~/utils/homeDashboard'

defineProps<{
  /** Данные панели; null — показывать нечего, панель не рисуется. */
  panel: ProjectPanel | null
  /** Подпись выбранного месяца для кнопки отчёта. */
  monthTitle: string
  /** Доступен ли платный блок «Счёт и акт». */
  billingEnabled: boolean
  /** Текст замка у платного блока. */
  billingBadge: string
}>()

const emit = defineEmits<{
  (event: 'open-group' | 'open-report' | 'open-card' | 'open-billing'): void
}>()

const open = defineModel<boolean>('open', { required: true })

const closeButton = ref<HTMLButtonElement | null>(null)

function closeDrawer() {
  open.value = false
}

/**
 * Escape закрывает панель.
 *
 * Слушатель на окне, а не на самой панели: закрытия по Escape сотрудник ждёт
 * из любого места, в том числе когда фокус стоит на кнопке действия внутри
 * панели. Вешаем его только на время, пока панель открыта, чтобы не
 * перехватывать Escape у дровера карточки проекта, который открывается поверх.
 */
function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeDrawer()
  }
}

watch(open, async (isOpen) => {
  if (typeof window === 'undefined') {
    return
  }

  if (!isOpen) {
    window.removeEventListener('keydown', handleKeydown)
    return
  }

  window.addEventListener('keydown', handleKeydown)

  // Фокус уводим внутрь панели: иначе он остался бы на строке таблицы под
  // оверлеем и Tab пошёл бы гулять по недоступному содержимому.
  await nextTick()
  closeButton.value?.focus()
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleKeydown)
  }
})
</script>

<template>
  <div
    v-if="open && panel"
    class="fixed inset-0 z-[9990] flex justify-end bg-slate-900/40 backdrop-blur-sm"
    @click="closeDrawer"
  >
    <aside
      role="dialog"
      aria-modal="true"
      :aria-label="`Проект: ${panel.name}`"
      class="flex h-full w-full max-w-full flex-col border-l border-slate-200 bg-white shadow-2xl min-[900px]:max-w-[460px]"
      @click.stop
    >
      <div class="border-b border-slate-200 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-lg font-semibold text-slate-900">{{ panel.name }}</div>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <span class="ms-pill" :class="getProjectStageClass(panel.stage)">{{ panel.stage }}</span>
              <span class="ms-pill bg-slate-100 text-slate-600">ID {{ panel.id }}</span>
            </div>
          </div>

          <button
            ref="closeButton"
            type="button"
            aria-label="Закрыть панель проекта"
            class="shrink-0 rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            @click="closeDrawer"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        <p class="text-xs text-slate-500">{{ panel.subtitle }}</p>

        <dl class="grid grid-cols-2 gap-3">
          <div v-for="stat in panel.stats" :key="stat.id" class="rounded-xl bg-slate-50 px-3 py-2">
            <dt class="text-[11px] font-medium uppercase tracking-[0.06em] text-slate-500">{{ stat.label }}</dt>
            <dd class="mt-0.5 text-sm font-semibold text-slate-900">{{ stat.value }}</dd>
          </div>
        </dl>

        <div class="flex flex-col gap-1.5">
          <button type="button" class="ms-action-card" @click="emit('open-group')">
            Группа проекта в Битрикс24
          </button>
          <button type="button" class="ms-action-card" @click="emit('open-report')">
            Отчёт по проекту за {{ monthTitle }}
          </button>
          <button type="button" class="ms-action-card" @click="emit('open-card')">
            Карточка проекта: ставка, юрлицо, сроки
          </button>
          <button
            type="button"
            class="ms-action-card flex items-center justify-between gap-2"
            :class="billingEnabled ? '' : 'cursor-not-allowed opacity-70'"
            @click="emit('open-billing')"
          >
            <span>Счёт и акт по часам проекта</span>
            <span v-if="!billingEnabled" class="ms-pill bg-amber-100 text-amber-800">
              {{ billingBadge }}
            </span>
          </button>
        </div>
      </div>

      <div class="border-t border-slate-200 px-5 py-4">
        <B24Button label="Закрыть" color="link" @click="closeDrawer" />
      </div>
    </aside>
  </div>
</template>
