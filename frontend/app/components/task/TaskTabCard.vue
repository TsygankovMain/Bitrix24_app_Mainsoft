<script setup lang="ts">
/**
 * Карточка задачи в дереве вкладки: заголовок с итогами, записи времени,
 * подзадачи и — там, куда нажали, — форма списания.
 *
 * Колонка одна на любой ширине. Прежняя вкладка делила фрейм на дерево и
 * панель правки (`1fr 380px`): при ширине фрейма 640 px дереву доставалось
 * около 230 px, а на 400 px вёрстка рассыпалась. Плотность теперь зависит от
 * ширины — что именно меняется, решает `resolveTaskTabLayout`.
 *
 * Кнопка «+» есть у каждой задачи и подзадачи: списание идёт на ту задачу, где
 * нажали, а не только на корневую.
 */
import { computed } from 'vue'
import type { TaskWorkspaceItem, TaskWorkspaceNode, TaskWorkspaceUser } from '~/types/task-workspace'
import { buildTaskTotalsSegments, formatTotalsText } from '~/utils/taskTabFormat'
import { taskTabIndent, type TaskTabLayout } from '~/utils/taskTabLayout'
import type { TaskEntryDraft, TaskFormAnchor } from '~/utils/taskTabEntry'
import TaskEntryForm from './TaskEntryForm.vue'
import TaskEntryRow from './TaskEntryRow.vue'

const props = defineProps<{
  node: TaskWorkspaceNode
  level: number
  layout: TaskTabLayout
  expandedTasks: Set<string>
  anchor: TaskFormAnchor | null
  draft: TaskEntryDraft | null
  users: TaskWorkspaceUser[]
  busy: boolean
}>()

const emit = defineEmits<{
  toggle: [taskId: string]
  create: [taskId: string]
  edit: [item: TaskWorkspaceItem, taskId: string]
  remove: [item: TaskWorkspaceItem]
  save: [draft: TaskEntryDraft]
  split: [draft: TaskEntryDraft]
  removeDraft: [draft: TaskEntryDraft]
  cancel: []
}>()

const isExpanded = computed(() => props.expandedTasks.has(props.node.taskId))
const totals = computed(() => buildTaskTotalsSegments(props.node))
const totalsText = computed(() => formatTotalsText(totals.value))
const indentStyle = computed(() => ({ marginLeft: `${taskTabIndent(props.level, props.layout)}px` }))
const entriesCount = computed(() => props.node.items?.length || 0)
const childrenCount = computed(() => props.node.children?.length || 0)

const isCreatingHere = computed(() =>
  props.anchor?.kind === 'create' && props.anchor.taskId === props.node.taskId && Boolean(props.draft)
)

function isEditingItem(item: TaskWorkspaceItem) {
  return props.anchor?.kind === 'edit' && String(props.anchor.itemId) === String(item.id)
}
</script>

<template>
    <div class="task-card" :style="indentStyle">
        <div class="task-card__head" :class="{ 'task-card__head--stacked': layout.stackedTaskTotals }">
            <button
                type="button"
                class="task-card__toggle"
                :aria-expanded="isExpanded"
                :aria-label="isExpanded ? 'Свернуть задачу' : 'Развернуть задачу'"
                @click="emit('toggle', node.taskId)"
            >
                <span class="material-symbols-outlined transition-transform" :class="{ 'rotate-180': isExpanded }">expand_more</span>
            </button>

            <div class="task-card__title-block">
                <div class="task-card__title" :title="node.taskTitle">
                    <span v-if="level > 0" class="task-card__badge">Подзадача</span>
                    {{ node.taskTitle }}
                </div>
                <div class="task-card__totals" :title="totalsText">
                    <span
                        v-for="segment in totals"
                        :key="segment.key"
                        class="task-card__total"
                        :class="`task-card__total--${segment.tone}`"
                    >
                        {{ segment.label }} <b>{{ segment.value }}</b>
                    </span>
                </div>
            </div>

            <button
                type="button"
                class="task-card__add"
                :title="`Списать часы на задачу «${node.taskTitle}»`"
                :aria-label="`Списать часы на задачу «${node.taskTitle}»`"
                @click="emit('create', node.taskId)"
            >
                <span class="material-symbols-outlined text-[20px] leading-none">add</span>
            </button>
        </div>

        <div v-if="isCreatingHere && draft" class="task-card__form">
            <TaskEntryForm
                :draft="draft"
                :users="users"
                :task-title="node.taskTitle"
                :layout="layout"
                :busy="busy"
                @save="emit('save', $event)"
                @split="emit('split', $event)"
                @remove="emit('removeDraft', $event)"
                @cancel="emit('cancel')"
            />
        </div>

        <div v-if="isExpanded" class="task-card__body">
            <template v-for="item in node.items" :key="item.id">
                <TaskEntryRow
                    :item="item"
                    :layout="layout"
                    :is-editing="isEditingItem(item)"
                    @edit="emit('edit', $event, node.taskId)"
                    @remove="emit('remove', $event)"
                />
                <TaskEntryForm
                    v-if="isEditingItem(item) && draft"
                    :draft="draft"
                    :users="users"
                    :task-title="node.taskTitle"
                    :layout="layout"
                    :busy="busy"
                    @save="emit('save', $event)"
                    @split="emit('split', $event)"
                    @remove="emit('removeDraft', $event)"
                    @cancel="emit('cancel')"
                />
            </template>

            <p v-if="entriesCount === 0 && childrenCount === 0" class="task-card__empty">
                Часы на эту задачу ещё не списывали.
            </p>

            <div v-if="childrenCount > 0" class="task-card__children">
                <TaskTabCard
                    v-for="child in node.children"
                    :key="child.taskId"
                    :node="child"
                    :level="level + 1"
                    :layout="layout"
                    :expanded-tasks="expandedTasks"
                    :anchor="anchor"
                    :draft="draft"
                    :users="users"
                    :busy="busy"
                    @toggle="emit('toggle', $event)"
                    @create="emit('create', $event)"
                    @edit="(item, taskId) => emit('edit', item, taskId)"
                    @remove="emit('remove', $event)"
                    @save="emit('save', $event)"
                    @split="emit('split', $event)"
                    @remove-draft="emit('removeDraft', $event)"
                    @cancel="emit('cancel')"
                />
            </div>
        </div>
    </div>
</template>

<style scoped>
.material-symbols-outlined {
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}

.task-card {
    overflow: hidden;
    margin-bottom: 8px;
    border: 1px solid var(--ui-color-base-6);
    border-radius: 12px;
    background: var(--ui-color-bg-content-primary);
}

.task-card__head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: var(--ui-color-bg-content-tertiary);
}

.task-card__toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    color: var(--ui-color-base-2);
    cursor: pointer;
}

.task-card__toggle:hover {
    background: var(--ui-color-base-7);
}

.task-card__title-block {
    display: flex;
    flex: 1;
    align-items: center;
    gap: 12px;
    min-width: 0;
}

.task-card__title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: 13px;
    font-weight: 600;
    color: var(--ui-color-base-1);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.task-card__badge {
    display: inline-block;
    margin-right: 6px;
    padding: 1px 6px;
    border-radius: 6px;
    background: var(--ui-color-accent-soft-blue-2);
    font-size: 11px;
    font-weight: 600;
    color: var(--ui-color-accent-main-link);
    vertical-align: middle;
}

/* Итоги задачи — одной строкой, а не тремя колонками, как было раньше. */
.task-card__totals {
    display: flex;
    flex-shrink: 0;
    flex-wrap: wrap;
    gap: 10px;
    font-size: 12px;
    color: var(--ui-color-base-2);
}

.task-card__total b {
    font-weight: 700;
}

.task-card__total--success b {
    color: var(--ui-color-green-90);
}

.task-card__total--danger b {
    color: var(--ui-color-red-80);
}

.task-card__total--muted b {
    color: var(--ui-color-base-2);
}

.task-card__add {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: var(--ui-color-blue-80);
    color: var(--ui-color-base-white-fixed);
    cursor: pointer;
}

.task-card__add:hover {
    background: var(--ui-color-blue-90);
}

.task-card__empty {
    padding: 10px 12px;
    border-top: 1px solid var(--ui-color-divider-default);
    font-size: 12px;
    color: var(--ui-color-base-2);
}

.task-card__children {
    padding: 8px 8px 0;
    border-top: 1px solid var(--ui-color-divider-default);
    background: var(--ui-color-bg-content-secondary);
}

/*
 * Узкий и средний фрейм: заголовок и итоги в две строки, кнопка «+» остаётся
 * на первой строке справа — до неё дотягиваются большим пальцем.
 */
.task-card__head--stacked {
    flex-wrap: wrap;
}

.task-card__head--stacked .task-card__title-block {
    flex-direction: column;
    align-items: stretch;
    gap: 4px;
}

.task-card__head--stacked .task-card__title {
    white-space: normal;
}
</style>
