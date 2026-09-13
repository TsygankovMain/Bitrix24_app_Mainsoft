<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { requestIframeAutoHeight } from '~/utils/iframe-resizer'
import { shouldShowSectionNavigation } from '~/utils/appNavigation'
import SectionNavigation from '~/components/nav/SectionNavigation.vue'
import MappingHealthBanner from '~/components/common/MappingHealthBanner.vue'

const route = useRoute()
const contentRef = ref<HTMLElement | null>(null)

/**
 * Постоянное меню разделов — только в полной версии приложения.
 *
 * Список экранов-исключений (вкладка задачи, слайдер, установка) живёт в
 * shouldShowSectionNavigation: это единственное место, где он проверяется, и
 * оно покрыто тестами.
 *
 * Почему два B24SidebarLayout, а не один с условным слотом: компонент решает,
 * рисовать ли шапку, по наличию слота `navbar`, и решает это ОДИН раз —
 * `isUseNavbar` внутри него вычисляется от `slots`, а slots не реактивны.
 * Условный `<template v-if #navbar>` в одном лейауте застрял бы на том
 * значении, которое было при первом рендере, и меню либо не появлялось бы на
 * страницах приложения, либо лезло бы во фрейм задачи. Разметка контента у
 * веток одна и та же, настройки — общий объект layoutUi ниже.
 */
const showNavigation = computed(() => shouldShowSectionNavigation(route.path))

const layoutUi = {
  root: 'h-dvh min-h-0 overflow-hidden',
  contentWrapper: 'flex-1 min-h-0 flex flex-col overflow-hidden',
  pageWrapper: 'min-h-0 flex-1 overflow-y-auto pb-6 scrollbar-thin scrollbar-transparent',
  container: 'mt-0 h-auto min-h-0 flex flex-col',
  containerWrapper: 'h-auto min-h-0 grow',
  containerWrapperInner: 'h-auto min-h-0'
}

let resizeObserver: ResizeObserver | null = null
let animationFrameId: number | null = null
let lastMeasuredHeight = 0

function syncIframeHeight(force = false) {
  if (typeof window === 'undefined') {
    return
  }

  if (animationFrameId !== null) {
    window.cancelAnimationFrame(animationFrameId)
  }

  animationFrameId = window.requestAnimationFrame(() => {
    animationFrameId = null

    nextTick(() => {
      const measuredHeight = Math.ceil(
        contentRef.value?.getBoundingClientRect().height
        || document.body.scrollHeight
        || document.documentElement.scrollHeight
      )

      if (!force && Math.abs(measuredHeight - lastMeasuredHeight) < 2) {
        return
      }

      lastMeasuredHeight = measuredHeight
      requestIframeAutoHeight()
    })
  })
}

const handleWindowResize = () => syncIframeHeight(true)

watch(() => route.fullPath, () => syncIframeHeight(true), { flush: 'post' })

onMounted(() => {
  syncIframeHeight(true)

  window.addEventListener('load', handleWindowResize)
  window.addEventListener('resize', handleWindowResize)

  if (typeof ResizeObserver !== 'undefined' && contentRef.value) {
    resizeObserver = new ResizeObserver(() => syncIframeHeight())
    resizeObserver.observe(contentRef.value)
  }
})

/**
 * Переключение веток лейаута (меню появилось или пропало) заменяет узел с
 * содержимым целиком, и наблюдатель остаётся висеть на выброшенном элементе —
 * высота фрейма после этого перестала бы пересчитываться. Перевешиваем его на
 * новый узел и заодно меряем заново.
 */
watch(contentRef, (element) => {
  if (!resizeObserver || !element) {
    return
  }

  resizeObserver.disconnect()
  resizeObserver.observe(element)
  syncIframeHeight(true)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()

  if (animationFrameId !== null) {
    window.cancelAnimationFrame(animationFrameId)
  }

  window.removeEventListener('load', handleWindowResize)
  window.removeEventListener('resize', handleWindowResize)
})
</script>

<template>
  <B24SidebarLayout
    v-if="showNavigation"
    :use-light-content="false"
    :b24ui="layoutUi"
  >
    <template #navbar>
      <SectionNavigation />
    </template>

    <div ref="contentRef" class="min-h-full w-full">
      <MappingHealthBanner />
      <slot />
    </div>
  </B24SidebarLayout>

  <B24SidebarLayout
    v-else
    :use-light-content="false"
    :b24ui="layoutUi"
  >
    <div ref="contentRef" class="min-h-full w-full">
      <slot />
    </div>
  </B24SidebarLayout>
</template>

<style scoped>
.--app {
  scrollbar-gutter: auto;
}
</style>
