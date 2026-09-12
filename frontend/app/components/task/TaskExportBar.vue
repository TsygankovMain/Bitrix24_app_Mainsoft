<script setup lang="ts">
/**
 * Выгрузки вкладки задачи: «В отчёт Битрикс24» и «Excel» плюс подтверждение
 * переноса.
 *
 * Вынесено в отдельный компонент, потому что на длинном дереве эта пара кнопок
 * выводится дважды — в строке инструментов наверху и блоком в конце вкладки
 * (почему так, а не `position: sticky`, расписано в
 * `utils/taskTabLayout.ts` → `shouldMirrorFooterActions`). Подтверждение
 * раскрывается там же, где нажали: если бы оно всегда жило внизу, человек,
 * нажавший верхнюю кнопку, увидел бы «ничего не произошло» — панель
 * подтверждения оказалась бы за нижним краем экрана.
 */

defineProps<{
  /** Показать подтверждение переноса вместо кнопок. */
  confirmOpen: boolean
  /** Перенос в процессе — кнопки заблокированы. */
  reporting: boolean
  /** Фильтр активен: переносится не всё, и молчать об этом нельзя. */
  filterActive: boolean
  /** Компактный вид для строки инструментов. */
  compact: boolean
}>()

const emit = defineEmits<{
  report: []
  confirm: []
  cancel: []
  exportCsv: []
}>()
</script>

<template>
    <div class="export-bar" :class="{ 'export-bar--compact': compact }">
        <div v-if="confirmOpen" class="export-bar__confirm">
            <p class="export-bar__text">
                Все записи с признаком «Учитывать» будут добавлены в задачи Битрикс24 как отработанное время.
            </p>
            <!-- Переносится то, что видно на экране: молчать про активный фильтр нельзя. -->
            <p v-if="filterActive" class="export-bar__text export-bar__text--warn">
                Фильтр активен — перенесутся только записи, попавшие под него.
            </p>
            <div class="export-bar__actions">
                <B24Button
                    :label="reporting ? 'Отправка…' : 'Подтвердить'"
                    color="air-primary"
                    :size="compact ? 'xs' : 'sm'"
                    :disabled="reporting"
                    @click="emit('confirm')"
                />
                <B24Button
                    label="Отмена"
                    color="air-secondary-no-accent"
                    :size="compact ? 'xs' : 'sm'"
                    :disabled="reporting"
                    @click="emit('cancel')"
                />
            </div>
        </div>

        <div v-else class="export-bar__actions">
            <B24Button
                label="В отчёт Битрикс24"
                color="air-secondary-no-accent"
                :size="compact ? 'xs' : 'sm'"
                @click="emit('report')"
            />
            <B24Button
                label="Excel"
                color="air-secondary-no-accent"
                :size="compact ? 'xs' : 'sm'"
                @click="emit('exportCsv')"
            />
        </div>
    </div>
</template>

<style scoped>
.export-bar {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.export-bar__confirm {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 12px;
    background: var(--ui-color-accent-soft-blue-3);
}

.export-bar--compact .export-bar__confirm {
    padding: 10px;
}

.export-bar__text {
    font-size: 13px;
    line-height: 1.5;
    color: var(--ui-color-base-1);
}

.export-bar--compact .export-bar__text {
    font-size: 12px;
}

.export-bar__text--warn {
    font-weight: 600;
    color: var(--ui-color-red-80);
}

.export-bar__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
</style>
