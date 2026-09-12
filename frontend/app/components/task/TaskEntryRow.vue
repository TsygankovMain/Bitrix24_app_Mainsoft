<script setup lang="ts">
/**
 * Строка записи времени в дереве задачи.
 *
 * Действия («Изменить» и «Удалить») видны всегда. Раньше они проявлялись
 * только при наведении — на планшете и телефоне указателя нет, наведения не
 * бывает, и записи оказывались нередактируемыми. Кнопки сделаны обычными, а не
 * пунктами выпадающего меню «⋯», сознательно: всплывающее меню рисуется
 * порталом с абсолютным позиционированием, а вкладка живёт в iframe, высоту
 * которого приложение подгоняет под содержимое — ровно та связка, из-за
 * которой пришлось убирать модальное окно формы. Двух кнопок здесь хватает,
 * меню не нужно.
 *
 * На узком фрейме подписи прячутся, остаются иконки размером 32×32 — это
 * минимальная зона касания, ниже которой промахиваются пальцем.
 */
import { computed } from 'vue'
import type { TaskWorkspaceItem } from '~/types/task-workspace'
import type { TaskTabLayout } from '~/utils/taskTabLayout'
import { formatEntryDate, formatTaskHours } from '~/utils/taskTabFormat'

const props = defineProps<{
  item: TaskWorkspaceItem
  layout: TaskTabLayout
  isEditing: boolean
}>()

const emit = defineEmits<{
  edit: [item: TaskWorkspaceItem]
  remove: [item: TaskWorkspaceItem]
}>()

const employeeName = computed(() => String(props.item.employeeName || '').trim() || 'Сотрудник не указан')
const entryDate = computed(() => formatEntryDate(props.item.date || props.item.createdTime))
const hoursLabel = computed(() => formatTaskHours(props.item.hours))
const description = computed(() => String(props.item.description || '').trim() || 'Без описания')
</script>

<template>
    <div
        class="entry-row"
        :class="{
            'entry-row--editing': isEditing,
            'entry-row--stacked': !layout.inlineEntryMeta
        }"
    >
        <span
            class="entry-row__dot"
            :class="item.isConsidered ? 'entry-row__dot--on' : 'entry-row__dot--off'"
            :title="item.isConsidered ? 'Учитывается в аналитике' : 'Не учитывается в аналитике'"
        />

        <div class="entry-row__main">
            <span class="entry-row__description" :title="description">{{ description }}</span>
            <span class="entry-row__meta">{{ employeeName }} · {{ entryDate }}</span>
        </div>

        <span
            class="entry-row__hours"
            :class="item.isConsidered ? 'entry-row__hours--on' : 'entry-row__hours--off'"
        >
            {{ hoursLabel }}
        </span>

        <div class="entry-row__actions">
            <button
                type="button"
                class="entry-row__action"
                :aria-label="`Изменить запись: ${description}`"
                title="Изменить"
                @click="emit('edit', item)"
            >
                <span class="material-symbols-outlined text-base leading-none">edit</span>
                <span v-if="!layout.iconOnlyEntryActions" class="entry-row__action-label">Изменить</span>
            </button>
            <button
                type="button"
                class="entry-row__action entry-row__action--danger"
                :aria-label="`Удалить запись: ${description}`"
                title="Удалить"
                @click="emit('remove', item)"
            >
                <span class="material-symbols-outlined text-base leading-none">delete</span>
                <span v-if="!layout.iconOnlyEntryActions" class="entry-row__action-label">Удалить</span>
            </button>
        </div>
    </div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

.entry-row {
    display: grid;
    align-items: center;
    gap: 4px 10px;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    padding: 8px 12px;
    border-top: 1px solid var(--ui-color-divider-default);
    background: var(--ui-color-bg-content-primary);
}

.entry-row:hover {
    background: var(--ui-color-accent-soft-blue-3);
}

.entry-row--editing {
    background: var(--ui-color-accent-soft-blue-3);
    box-shadow: inset 3px 0 0 var(--ui-color-blue-80);
}

.entry-row__dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
}

.entry-row__dot--on {
    background: var(--ui-color-green-90);
}

.entry-row__dot--off {
    background: var(--ui-color-red-80);
}

.entry-row__main {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
}

.entry-row__description {
    overflow: hidden;
    font-size: 13px;
    color: var(--ui-color-base-1);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.entry-row__meta {
    flex-shrink: 0;
    font-size: 12px;
    color: var(--ui-color-base-2);
    white-space: nowrap;
}

.entry-row__hours {
    font-size: 13px;
    font-weight: 700;
    white-space: nowrap;
}

.entry-row__hours--on {
    color: var(--ui-color-green-90);
}

.entry-row__hours--off {
    color: var(--ui-color-base-2);
}

.entry-row__actions {
    display: flex;
    align-items: center;
    gap: 4px;
}

.entry-row__action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    min-width: 32px;
    min-height: 32px;
    padding: 0 6px;
    border-radius: 8px;
    font-size: 12px;
    color: var(--ui-color-accent-main-link);
    cursor: pointer;
}

.entry-row__action:hover {
    background: var(--ui-color-accent-soft-blue-2);
}

.entry-row__action--danger {
    color: var(--ui-color-red-80);
}

.entry-row__action--danger:hover {
    background: var(--ui-color-red-20);
}

.entry-row__action-label {
    font-weight: 500;
}

/*
 * Узкий фрейм: мета уходит под описание, а колонки остаются те же — часы и
 * кнопки по-прежнему справа. Замер на 480 px: описанию достаётся 369 px
 * против 125 px, если оставить мету в строке. Переносить вниз ещё и часы
 * пробовали — строка вырастала до 80 px, то есть до трёх визуальных строк.
 */
.entry-row--stacked .entry-row__main {
    flex-direction: column;
    /*
     * Именно stretch, а не flex-start: при flex-start поперечный размер
     * описания считается по содержимому, и длинная строка вылезала за колонку
     * (замер на 400 px: 369 px в колонке шириной 190 px — текст наезжал на
     * часы и кнопки, а обрезала его только карточка задачи). При stretch
     * описание получает ширину колонки, и многоточие работает как задумано.
     */
    align-items: stretch;
    gap: 2px;
}
</style>
