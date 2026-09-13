import { computed, ref } from 'vue'
import { useB24Helper } from '@bitrix24/b24jssdk'
import {
  buildPresetsStorageKey,
  createPreset,
  findMatchingPreset,
  findPreset,
  normalizeFilterSnapshot,
  normalizePresetName,
  parsePresetsPayload,
  removePreset as removePresetFromList,
  serializePresets,
  upsertPreset,
  type ReportFilterPreset,
  type ReportFilterSnapshot,
} from '~/utils/reportFilterPresets'

/**
 * Пресеты строки фильтра: чтение и запись localStorage.
 *
 * Вся логика (разбор, слияние, сравнение наборов, подписи) живёт в
 * app/utils/reportFilterPresets.ts и покрыта тестами — здесь только доступ к
 * хранилищу и реактивная обёртка.
 *
 * Портал берём у помощника Битрикса (`hostName`), а не из адреса страницы:
 * приложение открыто во фрейме на СВОЁМ домене, одном для всех порталов, и
 * `location.hostname` пресеты разных порталов слил бы в одну кучу. Помощник
 * поднимается асинхронно, поэтому обращение обёрнуто в try/catch, а ключ умеет
 * работать без портала (см. buildPresetsStorageKey).
 */
export function useReportFilterPresets() {
  const { getB24Helper } = useB24Helper()
  const userStore = useUserStore()

  const presets = ref<ReportFilterPreset[]>([])
  const isReady = ref(false)

  function resolvePortalHost(): string {
    try {
      return getB24Helper()?.hostName || ''
    } catch {
      // Помощник ещё не инициализирован — это штатное состояние первых кадров.
      return ''
    }
  }

  function storageKey(): string {
    return buildPresetsStorageKey({
      portal: resolvePortalHost(),
      userId: userStore.id,
    })
  }

  function load(): void {
    if (typeof window === 'undefined') {
      return
    }

    try {
      presets.value = parsePresetsPayload(window.localStorage.getItem(storageKey()))
    } catch {
      // Приватный режим или запрещённое хранилище: живём без пресетов.
      presets.value = []
    } finally {
      isReady.value = true
    }
  }

  function persist(next: ReportFilterPreset[]): void {
    presets.value = next

    if (typeof window === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(storageKey(), serializePresets(next))
    } catch {
      // Квота или приватный режим: пресет останется только до перезагрузки.
    }
  }

  /** Сохранить текущий набор под именем. Возвращает пресет либо null, если имя пустое. */
  function save(name: string, snapshot: ReportFilterSnapshot): ReportFilterPreset | null {
    const cleanName = normalizePresetName(name)

    if (!cleanName) {
      return null
    }

    const preset = createPreset(cleanName, snapshot)
    persist(upsertPreset(presets.value, preset))

    return preset
  }

  function remove(id: string): void {
    persist(removePresetFromList(presets.value, id))
  }

  function get(id: string): ReportFilterPreset | null {
    return findPreset(presets.value, id)
  }

  /** Какой пресет соответствует текущему набору фильтров. */
  function matching(snapshot: ReportFilterSnapshot): ReportFilterPreset | null {
    return findMatchingPreset(presets.value, normalizeFilterSnapshot(snapshot))
  }

  return {
    presets: computed(() => presets.value),
    isReady: computed(() => isReady.value),
    load,
    save,
    remove,
    get,
    matching,
  }
}
