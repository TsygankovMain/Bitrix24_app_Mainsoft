<script setup lang="ts">
/**
 * Предупреждение «сопоставление полей не заполнено».
 *
 * До него приложение молчало: без сопоставления часы не пишутся, а отчёты,
 * счета и БДДС показывают пустые экраны — и человек делал вывод, что данных
 * нет. Сам экран настройки при этом был спрятан за кнопкой в карточке
 * «Конфигурация» внизу страницы настроек и в меню не значился вовсе.
 *
 * Живёт в лейауте (app/layouts/default.vue), то есть на всех экранах полной
 * версии приложения и ни на одном экране внутри карточек Битрикса: вкладка
 * задачи и слайдер идут другой ветвью лейаута (shouldShowSectionNavigation),
 * и там баннер и не нужен, и ломал бы высоту фрейма.
 *
 * Решение, ЧТО показывать, целиком в resolveMappingHealth (app/utils/
 * fieldMapping.ts) и покрыто тестами; здесь только разметка и момент
 * запроса. Запрос уходит по готовности токена: компонент лейаута рисуется
 * раньше бутстрапа страницы, поэтому ждём apiStore.hasToken.
 *
 * Баннер СВОРАЧИВАЕМЫЙ, но не закрываемый: администратор, который уже идёт
 * настраивать, не должен читать одно и то же на каждом экране, но и совсем
 * спрятать сообщение о неработающем приложении нельзя — свёрнутый вид
 * оставляет строку со ссылкой. Состояние свёртки живёт в общем состоянии
 * (useState), поэтому переход между экранами его не сбрасывает.
 */
import { computed, watch } from 'vue'
import { MAPPING_SETTINGS_ROUTE } from '~/composables/useMappingHealth'

const route = useRoute()
const apiStore = useApiStore()
const { health, load } = useMappingHealth()

const isCollapsed = useState<boolean>('app-mapping-health-collapsed', () => false)

watch(
  () => apiStore.hasToken,
  (ready) => {
    if (ready) {
      void load()
    }
  },
  { immediate: true }
)

/**
 * На самом экране настройки баннер не нужен: человек уже там, а состояние
 * настройки этот экран показывает подробнее и точнее.
 */
const isVisible = computed(() => {
  if (route.path.startsWith(MAPPING_SETTINGS_ROUTE)) {
    return false
  }

  return health.value.level !== 'ok'
})

const isCritical = computed(() => health.value.level === 'critical')

/** Первые несколько названий — остальное человек увидит на экране настройки. */
const shownMissing = computed(() => health.value.missingLabels.slice(0, 6))
const restMissingCount = computed(() => Math.max(0, health.value.missingLabels.length - shownMissing.value.length))
</script>

<template>
  <div
    v-if="isVisible"
    class="mapping-health"
    :class="isCritical ? 'mapping-health--critical' : 'mapping-health--warning'"
    role="status"
  >
    <div class="mapping-health__row">
      <span class="mapping-health__dot" aria-hidden="true" />
      <div class="mapping-health__body">
        <p class="mapping-health__title">
          {{ health.title }}
        </p>
        <template v-if="!isCollapsed">
          <p class="mapping-health__text">
            {{ health.text }}
          </p>
          <p v-if="shownMissing.length" class="mapping-health__missing">
            Не сопоставлено: {{ shownMissing.join(', ') }}<span v-if="restMissingCount"> и ещё {{ restMissingCount }}</span>.
          </p>
        </template>
      </div>
      <div class="mapping-health__actions">
        <NuxtLink :to="MAPPING_SETTINGS_ROUTE" class="mapping-health__link">
          {{ health.actionLabel || 'Открыть настройку полей' }}
        </NuxtLink>
        <button
          type="button"
          class="mapping-health__toggle"
          :aria-expanded="!isCollapsed"
          @click="isCollapsed = !isCollapsed"
        >
          {{ isCollapsed ? 'Подробнее' : 'Свернуть' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mapping-health {
  border-bottom: 1px solid transparent;
  padding: 10px 16px;
}

.mapping-health--critical {
  background: #fff1f2;
  border-bottom-color: #fecdd3;
  color: #9f1239;
}

.mapping-health--warning {
  background: #fffbeb;
  border-bottom-color: #fde68a;
  color: #92400e;
}

.mapping-health__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 0 auto;
  max-width: 1440px;
  width: 100%;
}

.mapping-health__dot {
  flex: 0 0 auto;
  margin-top: 6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentcolor;
}

.mapping-health__body {
  flex: 1 1 auto;
  min-width: 0;
}

.mapping-health__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
}

.mapping-health__text,
.mapping-health__missing {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.4;
}

.mapping-health__missing {
  opacity: 0.85;
}

.mapping-health__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.mapping-health__link,
.mapping-health__toggle {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 6px 12px;
  border: 1px solid currentcolor;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
  cursor: pointer;
}

.mapping-health__link {
  background: #fff;
}

.mapping-health__link:hover,
.mapping-health__toggle:hover {
  opacity: 0.8;
}

.mapping-health__link:focus-visible,
.mapping-health__toggle:focus-visible {
  outline: 2px solid currentcolor;
  outline-offset: 2px;
}

@media (max-width: 768px) {
  .mapping-health__row {
    flex-wrap: wrap;
  }

  .mapping-health__actions {
    width: 100%;
  }
}
</style>
