<script setup lang="ts">
/**
 * Постоянное меню разделов в шапке приложения — «вариант A: родной портал».
 *
 * Компонент только РИСУЕТ. Состав пунктов, активный пункт, свёртка в «Ещё» и
 * состояния платных функций живут в app/utils/appNavigation.ts и покрыты
 * тестами: node:test через tsx не резолвит .vue, и всё, что осталось бы здесь,
 * ревью проверить не смогло бы (тот же урок, что дала форма «Создать проект» —
 * см. докстринг CREATE_PROJECT_BUTTON_ENABLED в featureFlags.ts).
 *
 * Выпадающие списки нарисованы своей разметкой через именованный слот
 * `section-content`, а не штатным списком children: у B24NavigationMenu в
 * горизонтальной ориентации групп с заголовками внутри списка нет, а семь
 * отчётов одной колонкой читаются плохо.
 *
 * Счётчик проблем у «Контроля» компонент НЕ запрашивает сам: он читает
 * useState(NAV_CONTROL_ISSUES_STATE_KEY), который наполняет главная после
 * своей проверки месяца. Меню живёт в лейауте и рисуется раньше, чем приложение
 * получило токен, — свой запрос отсюда либо ушёл бы без авторизации, либо
 * дублировал бы уже сделанный.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import LockIcon from '@bitrix24/b24icons-vue/main/LockIcon'
import SettingsIcon from '@bitrix24/b24icons-vue/main/SettingsIcon'
import {
  buildAppNavigation,
  buildOverflowSection,
  isNavLinkActive,
  resolveActiveSectionId,
  splitNavigationByWidth,
  toNavigationMenuItems,
  NAV_CONTROL_ISSUES_STATE_KEY,
  SETTINGS_NAV_LINK,
  type NavLink,
  type NavSection,
} from '~/utils/appNavigation'

const route = useRoute()

/** Ширина, которую забирает шестерёнка справа. Ей место в ряду резервируем заранее. */
const SETTINGS_SLOT_WIDTH = 56

const controlIssues = useState<number | null>(NAV_CONTROL_ISSUES_STATE_KEY, () => null)

const barRef = ref<HTMLElement | null>(null)
const barWidth = ref(0)
const openSectionId = ref('')

let resizeObserver: ResizeObserver | null = null

function measure() {
  barWidth.value = Math.floor(barRef.value?.getBoundingClientRect().width || 0)
}

onMounted(() => {
  measure()

  if (typeof ResizeObserver !== 'undefined' && barRef.value) {
    resizeObserver = new ResizeObserver(() => measure())
    resizeObserver.observe(barRef.value)
  } else if (typeof window !== 'undefined') {
    window.addEventListener('resize', measure)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()

  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', measure)
  }
})

/**
 * Состояние подписки на платные функции решает СЕРВЕР (GET /api/features).
 *
 * Меню только читает готовое значение из общего состояния: своего запроса
 * отсюда сделать нельзя — компонент живёт в лейауте и рисуется раньше, чем
 * приложение получило JWT (та же причина, что у счётчика «Контроля» выше).
 * Спрашивает бутстрап, useAppInit.initApp.
 *
 * Пока ответа нет, access.locked = true, и пункт стоит с замком — ровно как
 * до появления функции. Мигание «замок -> рабочий пункт» при этом возможно,
 * и это осознанно лучше обратного: пункт без замка, ведущий на отказ.
 */
const { access: billingAccess } = useBillingFeature()
/**
 * У БДДС теперь тот же источник, что у счёта, — ответ /api/features.
 * До появления экранов здесь стояла фронтовая константа
 * FINANCE_BDDS_ENABLED; она осталась аварийным выключателем ВНУТРИ
 * resolveBddsAccess, а меню читает готовое решение, а не флаг.
 */
const { access: bddsAccess } = useBddsFeature()

const sections = computed<NavSection[]>(() => buildAppNavigation({
  controlIssuesCount: controlIssues.value,
  financeBddsEnabled: bddsAccess.value.enabled,
  financeBddsBadge: bddsAccess.value.badge,
  financeBillingEnabled: billingAccess.value.enabled,
  financeBillingBadge: billingAccess.value.badge,
}))

const split = computed(() => splitNavigationByWidth(
  sections.value,
  barWidth.value > 0 ? barWidth.value - SETTINGS_SLOT_WIDTH : 0
))

const overflowSection = computed(() => buildOverflowSection(split.value.overflow))

const shownSections = computed<NavSection[]>(() => (
  overflowSection.value ? [...split.value.visible, overflowSection.value] : split.value.visible
))

const activeSectionId = computed(() => resolveActiveSectionId(route.path, sections.value))

/** Активный раздел уехал в «Ещё» — горит «Ещё», иначе подсветка пропала бы совсем. */
const shownActiveId = computed(() => {
  const current = activeSectionId.value

  if (current && split.value.overflow.some(section => section.id === current)) {
    return 'more'
  }

  return current
})

const menuItems = computed(() => toNavigationMenuItems(shownSections.value, shownActiveId.value)
  .map(item => ({
    ...item,
    class: item.active
      ? 'text-[#0075ff] font-semibold'
      : undefined,
  })))

const isSettingsActive = computed(() => isNavLinkActive(route.path, SETTINGS_NAV_LINK))

/** Раскрытый список после перехода надо закрыть руками: ссылки в нём наши, не рековские. */
watch(() => route.fullPath, () => {
  openSectionId.value = ''
})

/**
 * Настройки классов у B24NavigationMenu — почему они тут, а не в теме.
 *
 * `viewportWrapper: z-50` — слой выпадающих списков над содержимым страницы.
 * В теме UI Kit сам viewport стоит на `z-[1]`, а стекинг-контекста между
 * шапкой и контентом страницы нет: значит любой элемент страницы с большим
 * z-index рисуется ПОВЕРХ раскрытого меню. Именно это и было на доске
 * проектов — липкие заголовки колонок канбана (`sticky top-0 z-10` плюс
 * полупрозрачный `bg-slate-50/95 backdrop-blur`, см. ProjectBoardColumn.vue)
 * проступали сквозь список «Отчётов», и со стороны это читалось как
 * полупрозрачное меню. Правим один раз здесь, а не z-index'ами на каждой
 * странице: 50 выше внутристраничных списков (z-30 у MultiSelectFilter и
 * ReportFilterBar) и ниже оверлеев и дроверов (z-[1000] у SearchableSelect и
 * ProgressOverlay, z-[9990] и выше у дроверов) — меню перекрывает страницу,
 * но не лезет поверх модальных окон.
 *
 * `content` — ширина и свой фон панели. Фон в теме лежит на viewport, а его
 * размер reka берёт из ResizeObserver'а элемента content; content же у
 * горизонтальной ориентации зафиксирован темой в `w-[240px]`
 * (compoundVariants, а twMerge съедает идущий раньше `w-full`). Пока ширину
 * задавал div ВНУТРИ слота, получалось 560 px содержимого в 240 px
 * закрашенной панели: правая часть списка оставалась без фона и обрезалась.
 * Поэтому ширина теперь на самом content, а на нём же непрозрачный фон —
 * viewport анимирует свой размер 200 мс, и на это время фон темы отстаёт от
 * содержимого. Значение ширины явное: про именованные `w-*`/`max-w-*` в
 * Tailwind 4 с UI Kit см. предупреждение в app/assets/css/main.css.
 */
const menuUi = {
  root: 'h-full w-full',
  viewportWrapper: 'z-50',
  content: 'w-[min(92vw,560px)] bg-white',
}

function sectionOf(item: unknown): NavSection | null {
  return (item as { section?: NavSection } | null)?.section || null
}

function linkClasses(link: NavLink) {
  return [
    'flex w-full flex-col gap-0.5 rounded-lg px-3 py-2 text-left transition',
    isNavLinkActive(route.path, link)
      ? 'bg-blue-50/60 text-[#0075ff]'
      : 'text-slate-700 hover:bg-slate-50',
  ]
}
</script>

<template>
  <div ref="barRef" class="h-full w-full min-w-0">
    <B24NavigationMenu
      v-model="openSectionId"
      :items="menuItems"
      orientation="horizontal"
      :b24ui="menuUi"
      aria-label="Разделы приложения"
    >
      <template #section-content="{ item }">
        <div class="w-full p-2">
          <div
            v-for="group in sectionOf(item)?.groups || []"
            :key="group.id"
            class="mb-1 last:mb-0"
          >
            <div class="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
              {{ group.label }}
            </div>
            <NuxtLink
              v-for="link in group.links"
              :key="link.id"
              :to="link.to"
              :class="linkClasses(link)"
              @click="openSectionId = ''"
            >
              <span class="flex items-center gap-2 text-sm font-medium">
                <LockIcon v-if="link.locked" class="size-4 shrink-0 text-slate-400" aria-hidden="true" />
                <span>{{ link.label }}</span>
                <span
                  v-if="link.badge"
                  class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
                >
                  {{ link.badge }}
                </span>
              </span>
              <span v-if="link.description" class="text-xs text-slate-500">
                {{ link.description }}
              </span>
            </NuxtLink>
          </div>
        </div>
      </template>

      <template #list-trailing>
        <NuxtLink
          :to="SETTINGS_NAV_LINK.to"
          class="ml-2 inline-flex size-9 shrink-0 items-center justify-center rounded-lg transition"
          :class="isSettingsActive ? 'bg-blue-50 text-[#0075ff]' : 'text-slate-500 hover:bg-slate-100'"
          :title="SETTINGS_NAV_LINK.label"
          :aria-label="SETTINGS_NAV_LINK.label"
        >
          <SettingsIcon class="size-5" aria-hidden="true" />
        </NuxtLink>
      </template>
    </B24NavigationMenu>
  </div>
</template>
