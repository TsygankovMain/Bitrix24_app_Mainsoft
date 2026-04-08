import type { B24Frame } from '@bitrix24/b24jssdk'
import type { Ref } from 'vue'
import { requestIframeAutoHeight, requestIframeFullHeight } from '@/utils/iframe-resizer'

export function resolveTaskPlacementOptions($b24: B24Frame | null) {
  const frame = $b24 as any
  let options = frame?.placement?.options || (frame?.placement?.info && frame.placement.info.options)

  if (!options && typeof window !== 'undefined' && typeof (window as any).BX24 !== 'undefined') {
    try {
      const rawInfo = (window as any).BX24.placement.info()
      if (rawInfo) {
        options = rawInfo.options
      }
    } catch (error) {
      console.warn('BX24.placement.info failed', error)
    }
  }

  return options || null
}

export function resolveTaskPlacementId($b24: B24Frame | null) {
  const options = resolveTaskPlacementOptions($b24)
  const taskId = options?.taskId || options?.ID || options?.id
  return taskId ? String(taskId) : null
}

export function canOpenNativeApplication() {
  return typeof window !== 'undefined'
    && typeof (window as any).BX24 !== 'undefined'
    && typeof (window as any).BX24.openApplication === 'function'
}

export function useIframeResizeOnToggle(source: Ref<boolean>, delayMs = 300) {
  watch(source, (isOpen) => {
    if (isOpen) {
      requestIframeFullHeight()
      return
    }

    setTimeout(() => requestIframeAutoHeight(), delayMs)
  })
}
