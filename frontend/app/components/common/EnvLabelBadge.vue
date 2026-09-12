<script setup lang="ts">
/**
 * Метка стенда поверх любого экрана — чтобы дев не спутать с продом.
 *
 * Живёт в корне приложения, поэтому видна и на страницах без лейаута
 * (вкладки задачи и группы). Клики пропускает сквозь себя: кнопки под ней
 * остаются рабочими. Снизу по центру стоит баннер устаревшей версии,
 * поэтому метка — сверху.
 */
import { normalizeEnvLabel } from '~/utils/envLabel'

const label = normalizeEnvLabel(useRuntimeConfig().public.envLabel)
</script>

<template>
  <div v-if="label" class="env-label" :title="`Стенд ${label}`">
    {{ label }}
  </div>
</template>

<style scoped>
.env-label {
  position: fixed;
  z-index: 1001;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  padding: 2px 12px;
  border-radius: 0 0 8px 8px;
  background: #e8590c;
  color: #fff;
  box-shadow: 0 2px 6px rgb(0 0 0 / 20%);
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  letter-spacing: 0.04em;
  pointer-events: none;
  user-select: none;
}
</style>
