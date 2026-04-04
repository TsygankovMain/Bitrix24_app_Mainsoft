<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { requestIframeAutoHeight } from '~/utils/iframe-resizer'

const route = useRoute()
const contentRef = ref<HTMLElement | null>(null)

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
    :use-light-content="false"
    :b24ui="{
      root: 'min-h-full',
      contentWrapper: 'flex-1 min-h-0 flex flex-col',
      pageWrapper: 'min-h-full pb-6',
      container: 'mt-0 h-auto min-h-full',
      containerWrapper: 'h-auto min-h-full',
      containerWrapperInner: 'h-auto min-h-full'
    }"
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
