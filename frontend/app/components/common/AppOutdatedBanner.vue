<script setup lang="ts">
/**
 * Баннер «вкладка работает на старой сборке».
 *
 * Показывается, когда сервер отклонил запись с кодом app_version_mismatch.
 * Раньше человек видел только тост с текстом «перезагрузите страницу» — и
 * должен был сообразить, что перезагружать нужно САМ ФРЕЙМ, а не страницу
 * Битрикса вокруг него (жёсткое обновление внешней страницы содержимое
 * фрейма не меняет — инцидент 31.08.2026). Кнопка снимает этот вопрос.
 *
 * Живёт в корне приложения, чтобы не заводить обработчик на каждом экране:
 * отказ по версии может прийти на любую пишущую операцию.
 */
const { isOutdated, reloadApp } = useAppOutdated()
</script>

<template>
  <div v-if="isOutdated" class="app-outdated" role="alert">
    <div class="app-outdated__text">
      <strong>Приложение обновилось.</strong>
      Эта вкладка работает на старой версии, поэтому изменения не сохраняются.
    </div>
    <B24Button
      label="Обновить страницу"
      color="primary"
      size="sm"
      @click="reloadApp"
    />
  </div>
</template>

<style scoped>
.app-outdated {
  position: fixed;
  z-index: 1000;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: min(640px, calc(100vw - 32px));
  padding: 12px 16px;
  border-radius: 12px;
  background: #2b3038;
  color: #fff;
  box-shadow: 0 8px 24px rgb(0 0 0 / 25%);
  font-size: 13px;
  line-height: 1.4;
}

.app-outdated__text {
  flex: 1 1 auto;
}
</style>
