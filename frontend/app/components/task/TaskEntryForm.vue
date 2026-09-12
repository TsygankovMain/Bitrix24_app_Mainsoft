<script setup lang="ts">
/**
 * Форма списания часов, раскрывающаяся прямо в списке.
 *
 * Почему не модальное окно. Вкладка задачи живёт в iframe, высоту которого
 * приложение само подгоняет под содержимое (`requestIframeAutoHeight` →
 * `BX24.fitWindow`). Центрированное по фрейму окно при длинном дереве задач
 * оказывается за пределами того куска страницы, который человек видит: фрейм
 * высотой 3000 px, окно по центру — на 1500-й, а смотрит человек на первый
 * экран. Инлайн-форма такого класса ошибок не имеет в принципе: она появляется
 * ровно там, куда нажали.
 *
 * Форма работает с копией черновика и отдаёт результат событием. Прямая
 * правка объекта из пропа ломала бы отмену (значения уже изменены) и
 * нарушала бы `vue/no-mutating-props`.
 */
import { computed, reactive, ref, watch } from 'vue'
import type { TaskWorkspaceUser } from '~/types/task-workspace'
import type { TaskTabLayout } from '~/utils/taskTabLayout'
import {
  quickDateOptions,
  quickHourOptions,
  validateEntryDraft,
  validateSplit,
  type TaskEntryDraft
} from '~/utils/taskTabEntry'

const props = defineProps<{
  draft: TaskEntryDraft
  users: TaskWorkspaceUser[]
  taskTitle: string
  layout: TaskTabLayout
  busy: boolean
}>()

const emit = defineEmits<{
  save: [draft: TaskEntryDraft]
  split: [draft: TaskEntryDraft]
  remove: [draft: TaskEntryDraft]
  cancel: []
}>()

const form = reactive<TaskEntryDraft>({ ...props.draft })
const isSplitOpen = ref(false)
const errorText = ref<string | null>(null)

watch(() => props.draft, (next) => {
  Object.assign(form, next)
  isSplitOpen.value = false
  errorText.value = null
})

const isEditing = computed(() => Boolean(form.id))
const dateShortcuts = computed(() => quickDateOptions(new Date()))
const hourShortcuts = quickHourOptions()

function userLabel(user: TaskWorkspaceUser) {
  const name = `${user.NAME ?? ''} ${user.LAST_NAME ?? ''}`.trim()
  return name || `Сотрудник ${user.ID}`
}

function setHours(value: number) {
  form.hours = value
}

function setDate(value: string) {
  form.date = value
}

function submit() {
  const error = validateEntryDraft(form)
  errorText.value = error
  if (error) {
    return
  }

  emit('save', { ...form })
}

function submitSplit() {
  const error = validateSplit(form)
  errorText.value = error
  if (error) {
    return
  }

  emit('split', { ...form })
}
</script>

<template>
    <div class="entry-form" :class="{ 'entry-form--narrow': layout.mode === 'narrow' }">
        <div class="entry-form__head">
            <span class="entry-form__title">
                {{ isEditing ? 'Правка записи' : 'Списание часов' }}
            </span>
            <span class="entry-form__task" :title="taskTitle">{{ taskTitle }}</span>
        </div>

        <div class="entry-form__grid">
            <label class="entry-form__field entry-form__field--wide">
                <span class="entry-form__label">Описание</span>
                <textarea
                    v-model="form.description"
                    rows="2"
                    class="resize-none"
                    placeholder="Что сделано"
                />
            </label>

            <label class="entry-form__field">
                <span class="entry-form__label">Сотрудник</span>
                <select v-model="form.employeeId">
                    <option v-for="user in users" :key="String(user.ID)" :value="user.ID">
                        {{ userLabel(user) }}
                    </option>
                </select>
            </label>

            <div class="entry-form__field">
                <span class="entry-form__label">Дата</span>
                <input v-model="form.date" type="date">
                <div class="entry-form__quick">
                    <button
                        v-for="shortcut in dateShortcuts"
                        :key="shortcut.value"
                        type="button"
                        class="entry-form__chip"
                        :class="{ 'entry-form__chip--on': form.date === shortcut.value }"
                        :aria-label="`Поставить дату: ${shortcut.label.toLowerCase()}`"
                        @click="setDate(shortcut.value)"
                    >
                        {{ shortcut.label }}
                    </button>
                </div>
            </div>

            <div class="entry-form__field">
                <span class="entry-form__label">Часы</span>
                <input v-model.number="form.hours" type="number" step="0.25" min="0" class="font-semibold">
                <div class="entry-form__quick">
                    <button
                        v-for="option in hourShortcuts"
                        :key="option.value"
                        type="button"
                        class="entry-form__chip"
                        :class="{ 'entry-form__chip--on': form.hours === option.value }"
                        :aria-label="`Поставить ${option.label} часа`"
                        @click="setHours(option.value)"
                    >
                        {{ option.label }}
                    </button>
                </div>
            </div>

            <label class="entry-form__toggle entry-form__field--wide">
                <input v-model="form.isConsidered" type="checkbox">
                <span>Учитывать в аналитике</span>
            </label>
        </div>

        <p v-if="errorText" class="entry-form__error" role="alert">{{ errorText }}</p>

        <div v-if="isEditing" class="entry-form__split">
            <button type="button" class="entry-form__split-toggle" @click="isSplitOpen = !isSplitOpen">
                <span class="material-symbols-outlined text-base leading-none">call_split</span>
                Разделить запись
                <span class="material-symbols-outlined text-base leading-none" :class="{ 'rotate-180': isSplitOpen }">expand_more</span>
            </button>

            <div v-if="isSplitOpen" class="entry-form__split-body">
                <p class="entry-form__hint">
                    Часть часов уйдёт в новую запись, в исходной останется остаток.
                </p>
                <div class="entry-form__split-row">
                    <input v-model.number="form.splitHours" type="number" step="0.5" min="0" placeholder="0">
                    <span class="entry-form__hint">часов отделить</span>
                </div>
                <label class="entry-form__toggle">
                    <input v-model="form.splitInvert" type="checkbox">
                    <span>У отделённой части перевернуть признак «Учитывать»</span>
                </label>
                <B24Button
                    label="Выполнить разделение"
                    color="air-secondary-no-accent"
                    size="sm"
                    :disabled="busy"
                    @click="submitSplit"
                />
            </div>
        </div>

        <div class="entry-form__actions">
            <B24Button
                :label="isEditing ? 'Сохранить' : 'Списать часы'"
                color="air-primary"
                :disabled="busy"
                @click="submit"
            />
            <B24Button
                label="Отмена"
                color="air-secondary-no-accent"
                :disabled="busy"
                @click="emit('cancel')"
            />
            <button
                v-if="isEditing"
                type="button"
                class="entry-form__delete"
                :disabled="busy"
                @click="emit('remove', { ...form })"
            >
                <span class="material-symbols-outlined text-base leading-none">delete</span>
                Удалить
            </button>
        </div>
    </div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

.entry-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border-top: 1px solid var(--ui-color-divider-accent);
    background: var(--ui-color-accent-soft-blue-3);
}

.entry-form__head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
}

.entry-form__title {
    font-size: 14px;
    font-weight: 600;
    color: var(--ui-color-base-1);
}

.entry-form__task {
    min-width: 0;
    overflow: hidden;
    font-size: 12px;
    color: var(--ui-color-base-2);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.entry-form__grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.entry-form--narrow .entry-form__grid {
    grid-template-columns: minmax(0, 1fr);
}

.entry-form__field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
}

.entry-form__field--wide {
    grid-column: 1 / -1;
}

.entry-form__label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ui-color-base-2);
}

.entry-form__quick {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.entry-form__chip {
    min-height: 28px;
    padding: 4px 10px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 8px;
    background: var(--ui-color-base-8);
    font-size: 12px;
    color: var(--ui-color-base-2);
    cursor: pointer;
}

.entry-form__chip:hover {
    border-color: var(--ui-color-accent-main-link);
    color: var(--ui-color-accent-main-link);
}

.entry-form__chip--on {
    border-color: var(--ui-color-accent-main-link);
    background: var(--ui-color-accent-soft-blue-2);
    color: var(--ui-color-accent-main-link);
    font-weight: 600;
}

.entry-form__toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    font-size: 13px;
    color: var(--ui-color-base-1);
    cursor: pointer;
}

.entry-form__toggle input {
    width: 16px;
    height: 16px;
    accent-color: var(--ui-color-blue-80);
}

.entry-form__error {
    font-size: 13px;
    font-weight: 500;
    color: var(--ui-color-red-80);
}

.entry-form__split {
    border: 1px solid var(--ui-color-base-6);
    border-radius: 10px;
    background: var(--ui-color-base-8);
}

.entry-form__split-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    min-height: 36px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 500;
    color: var(--ui-color-base-2);
    cursor: pointer;
}

.entry-form__split-body {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 0 12px 12px;
}

.entry-form__split-row {
    display: flex;
    align-items: center;
    gap: 8px;
}

.entry-form__split-row input {
    width: 110px;
}

.entry-form__hint {
    font-size: 12px;
    line-height: 1.5;
    color: var(--ui-color-base-2);
}

.entry-form__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
}

.entry-form__delete {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
    margin-left: auto;
    padding: 0 12px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    color: var(--ui-color-red-80);
    cursor: pointer;
}

.entry-form__delete:hover {
    background: var(--ui-color-red-20);
}

.entry-form__delete:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
</style>
