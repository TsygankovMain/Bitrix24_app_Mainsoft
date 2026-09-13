<script setup lang="ts">
/**
 * Таблица операций поступлений и списаний. Одна на два экрана.
 *
 * Используется и на карточке проекта БДДС, и в реестре всех операций.
 * Второй таблицы не заводится намеренно: колонки, знаки сумм и переход в
 * CRM там одни и те же, а две копии разъехались бы на первой же правке.
 * Разница между экранами — только в колонке «Проект» (в реестре нужна, на
 * карточке это та же строка в каждой ячейке) и в тексте пустого состояния.
 *
 * Компонент НЕ считает и не ходит в сеть: строки приходят уже разобранными
 * (utils/bddsOperations.ts), запросы делают страницы. Здесь только разметка
 * и три состояния списка:
 *
 *  1. смарт-процесс не настроен — отказ с кнопкой, ведущей прямо на шаг
 *     «Доходы-расходы» экрана сопоставления (адрес — страница, событие
 *     open-settings). Это не «операций нет»: приложение работает, не
 *     заполнена настройка. Технического адреса в тексте нет: человеку он
 *     ничего не говорит, а ведёт туда кнопка;
 *  2. операций нет — текст даёт страница, потому что он зависит от того,
 *     стоят ли фильтры;
 *  3. строки.
 *
 * Ширины таблицы заданы явным значением (min-w-[860px]), а не именованной
 * утилитой вида max-w-lg: в этом проекте их шкала падает на --spacing темы
 * UI Kit, и max-w-lg даёт 20 px вместо 512 px.
 */
import {
  BDDS_OPERATIONS_NOT_CONFIGURED_TEXT,
  BDDS_OPERATIONS_NOT_CONFIGURED_TITLE,
  BDDS_OPERATIONS_SETTINGS_LABEL,
  BDDS_OPERATIONS_SETTINGS_WHO,
  BDDS_OPERATIONS_TRUNCATED_TEXT,
  formatBddsOperationAuthor,
  formatBddsOperationDate,
  formatBddsOperationSignedAmount,
  formatBddsOperationSource,
  type BddsOperationRow,
} from '~/utils/bddsOperations'
import { openCrmItemCard } from '~/utils/openCrmItem'

const props = withDefaults(defineProps<{
  rows: BddsOperationRow[]
  /** id сотрудника -> имя. Нет в справочнике — покажем id, а не пустоту. */
  authorNames?: Record<string, string> | null
  /** project_item_id -> название проекта. Нужно только реестру. */
  projectNames?: Record<string, string> | null
  showProject?: boolean
  /** entityTypeId смарт-процесса: без него ссылка в CRM не собирается. */
  entityTypeId?: number | null
  loading?: boolean
  hasMore?: boolean
  truncated?: boolean
  /** Смарт-процесс операций не настроен — вместо списка отказ. */
  notConfigured?: boolean
  emptyText: string
}>(), {
  authorNames: null,
  projectNames: null,
  showProject: false,
  entityTypeId: null,
  loading: false,
  hasMore: false,
  truncated: false,
  notConfigured: false,
})

const emit = defineEmits<{
  'load-more': []
  'open-settings': []
}>()

/** Переход в элемент смарт-процесса. Без entityTypeId ссылки нет вовсе. */
function openOperation(row: BddsOperationRow) {
  if (!props.entityTypeId || !row.id) {
    return
  }

  openCrmItemCard(props.entityTypeId, row.id)
}

function projectName(row: BddsOperationRow): string {
  if (!row.projectItemId) {
    return 'без проекта'
  }

  return props.projectNames?.[row.projectItemId] || `элемент #${row.projectItemId}`
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="notConfigured" class="ms-panel-warning">
      <p class="font-medium">{{ BDDS_OPERATIONS_NOT_CONFIGURED_TITLE }}</p>
      <p class="mt-1 text-sm">{{ BDDS_OPERATIONS_NOT_CONFIGURED_TEXT }}</p>
      <div class="mt-2 flex flex-wrap items-center gap-3">
        <B24Button
          :label="BDDS_OPERATIONS_SETTINGS_LABEL"
          color="default"
          size="sm"
          @click="emit('open-settings')"
        />
        <span class="text-xs text-amber-700">{{ BDDS_OPERATIONS_SETTINGS_WHO }}</span>
      </div>
    </div>

    <template v-else>
      <p v-if="!rows.length && !loading" class="text-sm text-slate-500">{{ emptyText }}</p>

      <div v-if="rows.length" class="ms-table-shell">
        <table class="ms-table min-w-[860px]">
          <thead>
            <tr>
              <th>Дата</th>
              <th v-if="showProject">Проект</th>
              <th>Тип</th>
              <th class="text-right">Сумма</th>
              <th>Назначение</th>
              <th>Комментарий</th>
              <th>Автор</th>
              <th>Источник</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="row.id || `row-${index}`">
              <td class="whitespace-nowrap">{{ formatBddsOperationDate(row.date) }}</td>
              <td v-if="showProject" class="text-slate-700">{{ projectName(row) }}</td>
              <td>
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="row.type === 'income'
                    ? 'bg-emerald-50 text-emerald-700'
                    : (row.type === 'expense' ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-500')"
                >
                  {{ row.typeLabel }}
                </span>
              </td>
              <td
                class="whitespace-nowrap text-right font-semibold"
                :class="row.type === 'income'
                  ? 'text-emerald-700'
                  : (row.type === 'expense' ? 'text-rose-700' : 'text-slate-500')"
              >
                {{ formatBddsOperationSignedAmount(row) }}
              </td>
              <td class="text-slate-700">{{ row.purpose || '—' }}</td>
              <td class="text-slate-500">{{ row.comment || '—' }}</td>
              <td class="whitespace-nowrap text-slate-500">
                {{ formatBddsOperationAuthor(row.authorId, authorNames) }}
              </td>
              <td class="whitespace-nowrap text-slate-500">{{ formatBddsOperationSource(row.source) }}</td>
              <td class="whitespace-nowrap text-right">
                <B24Button
                  v-if="entityTypeId && row.id"
                  label="В CRM"
                  color="link"
                  size="sm"
                  @click="openOperation(row)"
                />
                <span v-else class="text-xs text-slate-400">без ссылки</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="truncated" class="ms-panel-warning">{{ BDDS_OPERATIONS_TRUNCATED_TEXT }}</p>

      <div v-if="hasMore" class="flex justify-center">
        <B24Button
          label="Показать ещё"
          color="default"
          :loading="loading"
          @click="emit('load-more')"
        />
      </div>

      <p v-else-if="rows.length && !truncated" class="text-xs text-slate-400">
        Это все операции выборки.
      </p>
    </template>
  </div>
</template>
