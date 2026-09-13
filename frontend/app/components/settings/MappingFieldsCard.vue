<script setup lang="ts">
/**
 * Блок сопоставления полей одного смарт-процесса.
 *
 * Один компонент на все блоки экрана (списания, карточки проектов,
 * «Доходы-расходы»): наборы
 * полей разные, а разметка строки одна и та же, и дублировать её дважды по
 * шестьдесят строк — гарантированный расход двух правд.
 *
 * Что здесь изменилось против прежней таблицы:
 *
 * - поля СГРУППИРОВАНЫ по тому, что сломается без них, и группа
 *   «необязательные» по умолчанию свёрнута. Раньше все 15 строк лежали
 *   плоским списком, и понять, с каких начинать, было нельзя;
 * - у незаполненного обязательного поля видно ПОСЛЕДСТВИЕ («Без него:
 *   отчёты по сотрудникам останутся пустыми»), а не только тип;
 * - «Создать поле» — отдельная кнопка. Раньше это был пункт внутри
 *   выпадающего списка («+ Создать поле …»), то есть выбор из списка
 *   молча выполнял запись на портал: ловушка, из которой нельзя выйти
 *   отменой;
 * - поля неподходящего типа больше не исчезают из списка, а лежат отдельной
 *   группой с честной подписью. Раньше при строковом поле под дату список
 *   выглядел пустым без объяснения;
 * - подпись строки — это `<label for>` своего select'а, поэтому она
 *   читается скринридером и по ней можно кликнуть.
 *
 * Компонент только рисует и сообщает о действиях наверх. Вся логика —
 * app/utils/fieldMapping.ts, под тестами.
 */
import { computed } from 'vue'
import {
  buildFieldOptionGroups,
  isMappedFieldMissing,
  type MappingBlockId,
  type MappingBlockStatus,
  type MappingRow,
  type MappingSuggestion,
} from '~/utils/fieldMapping'
import type { SmartProcessFieldOption } from '~/types/config'

const props = defineProps<{
  block: MappingBlockId
  rows: MappingRow[]
  status: MappingBlockStatus
  mapping: Record<string, string>
  spFields: SmartProcessFieldOption[]
  /** null — автоподбор ещё не запускали. */
  suggestions: MappingSuggestion[] | null
  suggestionsNote: string
  isSuggesting: boolean
  isLoadingFields: boolean
  creatingKey: string | null
  highlightKey: string
  canEdit: boolean
  /** Показывать ли, что все поля блока обязательны для сервера. */
  allRequiredNote?: string
}>()

const emit = defineEmits<{
  change: [key: string, value: string]
  create: [key: string, label: string]
  suggest: []
  applySuggestions: []
  dismissSuggestions: []
  reloadFields: []
}>()

type RowGroup = {
  id: string
  title: string
  hint: string
  rows: MappingRow[]
  collapsedByDefault: boolean
}

const groups = computed<RowGroup[]>(() => {
  const byImportance = (importance: MappingRow['importance']) =>
    props.rows.filter(row => row.importance === importance)

  const result: RowGroup[] = []
  const critical = byImportance('critical')
  const reports = byImportance('reports')
  const optional = byImportance('optional')

  const isFinance = props.block === 'finance'

  if (critical.length) {
    const criticalHint: Record<MappingBlockId, string> = {
      timesheet: 'Часы не запишутся и не прочитаются.',
      project: 'Сервер не примет конфигурацию, пока хотя бы одно поле пустое.',
      finance: 'Без любого из них экран «Операции по проектам» пишет «не настроен», а добавить операцию нельзя. Сохранить черновик при этом можно.',
    }
    result.push({
      id: 'critical',
      title: isFinance ? 'Без этих полей операции не работают' : 'Без этих полей приложение не работает',
      hint: criticalHint[props.block],
      rows: critical,
      collapsedByDefault: false,
    })
  }

  if (reports.length) {
    result.push({
      id: 'reports',
      title: isFinance ? 'Без этих полей операции теряют данные' : 'Без этих полей отчёты и документы врут',
      hint: isFinance
        ? 'Операции читаются и заводятся, но часть сведений не сохранится.'
        : 'Учёт часов работает, но цифры будут неполными.',
      rows: reports,
      collapsedByDefault: false,
    })
  }

  if (optional.length) {
    result.push({
      id: 'optional',
      title: 'Необязательные',
      hint: 'Цифры верны и без них, теряется только удобство.',
      rows: optional,
      collapsedByDefault: true,
    })
  }

  return result
})

function selectId(row: MappingRow): string {
  return `mapping-${props.block}-${row.key}`
}

function rowAnchor(row: MappingRow): string {
  return `field-${props.block}-${row.key}`
}

function mappedValue(row: MappingRow): string {
  return String(props.mapping[row.key] || '').trim()
}

function isMissing(row: MappingRow): boolean {
  return !mappedValue(row)
}

function isBroken(row: MappingRow): boolean {
  return isMappedFieldMissing(mappedValue(row), props.spFields)
}

function optionGroups(row: MappingRow) {
  return buildFieldOptionGroups(row, props.spFields, mappedValue(row))
}

function onSelectChange(row: MappingRow, event: Event) {
  const select = event.target as HTMLSelectElement | null
  emit('change', row.key, select?.value || '')
}

const groupMissingCount = (group: RowGroup) => group.rows.filter(isMissing).length

/** Порядок: сначала точное по коду установки, потом по названию и коду, риск по типу — в конце. */
const sortedSuggestions = computed(() => {
  const rank: Record<MappingSuggestion['source'], number> = { install: 0, label: 1, code: 2, type: 3 }
  return [...(props.suggestions || [])].sort((a, b) => rank[a.source] - rank[b.source])
})
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-slate-600">
      {{ status.nextStep }}
    </p>

    <p v-if="allRequiredNote" class="ms-note ms-note-info">
      {{ allRequiredNote }}
    </p>

    <!--
      Автоподбор.

      Показывается ЗАМЕТНО и до сохранения: сначала «что нашлось», потом
      решение человека. Автоподбор в stores/fieldConfig.ts работает иначе —
      сразу пишет в app.option и только у администратора; здесь он ничего не
      сохраняет, поэтому неверную догадку можно просто не применять.
    -->
    <div class="ms-panel-muted">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-sm font-semibold text-slate-900">Подобрать поля автоматически</p>
          <p class="mt-1 text-xs text-slate-500">
            Приложение сопоставит пустые строки по названиям и кодам полей смарт-процесса и покажет
            результат здесь же. Ничего не сохранится, пока вы не нажмёте «Применить».
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <B24Button
            label="Подобрать автоматически"
            color="primary"
            size="sm"
            :loading="isSuggesting"
            :disabled="!canEdit || isSuggesting || !spFields.length"
            @click="emit('suggest')"
          />
          <B24Button
            label="Обновить список полей"
            color="default"
            size="sm"
            :loading="isLoadingFields"
            :disabled="!status.entityTypeId || isLoadingFields"
            @click="emit('reloadFields')"
          />
        </div>
      </div>

      <div v-if="suggestions" class="mt-3 space-y-3">
        <p class="text-sm text-slate-700">{{ suggestionsNote }}</p>

        <ul v-if="sortedSuggestions.length" class="space-y-2">
          <li
            v-for="item in sortedSuggestions"
            :key="`suggestion-${block}-${item.key}`"
            class="rounded-xl border bg-white px-3 py-2"
            :class="item.source === 'type' ? 'border-amber-300' : 'border-slate-200'"
          >
            <div class="flex flex-wrap items-baseline gap-2">
              <span class="text-sm font-semibold text-slate-900">{{ item.label }}</span>
              <span class="text-slate-400" aria-hidden="true">→</span>
              <span class="text-sm text-slate-700">{{ item.fieldTitle }}</span>
              <span class="font-mono text-[11px] text-slate-400">{{ item.fieldId }}</span>
              <span
                v-if="item.source === 'type'"
                class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800"
              >
                проверьте
              </span>
              <span
                v-else-if="item.source === 'install'"
                class="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700"
              >
                точно по коду
              </span>
            </div>
            <p class="mt-1 text-xs text-slate-500">{{ item.reason }}</p>
          </li>
        </ul>

        <div class="flex flex-wrap gap-2">
          <B24Button
            v-if="sortedSuggestions.length"
            :label="`Применить (${sortedSuggestions.length})`"
            color="success"
            size="sm"
            :disabled="!canEdit"
            @click="emit('applySuggestions')"
          />
          <B24Button
            label="Не применять"
            color="link"
            size="sm"
            @click="emit('dismissSuggestions')"
          />
        </div>
      </div>
    </div>

    <div v-if="!spFields.length" class="ms-note ms-note-info">
      Список полей смарт-процесса пуст. Нажмите «Обновить список полей»: пока приложение не знает
      полей портала, сопоставлять не из чего.
    </div>

    <section
      v-for="group in groups"
      :key="`group-${block}-${group.id}`"
      class="rounded-2xl border border-slate-200 bg-white"
    >
      <details :open="!group.collapsedByDefault || groupMissingCount(group) > 0">
        <summary class="flex cursor-pointer flex-wrap items-center gap-2 px-4 py-3">
          <span class="text-sm font-semibold text-slate-900">{{ group.title }}</span>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
            :class="groupMissingCount(group)
              ? (group.id === 'optional' ? 'bg-slate-100 text-slate-500' : 'bg-rose-100 text-rose-700')
              : 'bg-emerald-100 text-emerald-700'"
          >
            {{ groupMissingCount(group) ? `осталось ${groupMissingCount(group)}` : 'готово' }}
          </span>
          <span class="w-full text-xs text-slate-500">{{ group.hint }}</span>
        </summary>

        <div class="divide-y divide-slate-100 border-t border-slate-100">
          <div
            v-for="row in group.rows"
            :id="rowAnchor(row)"
            :key="`row-${block}-${row.key}`"
            class="grid gap-3 px-4 py-3 md:grid-cols-2"
            :class="highlightKey === `${block}:${row.key}` ? 'bg-amber-50' : ''"
          >
            <div class="min-w-0">
              <label :for="selectId(row)" class="block text-sm font-semibold text-slate-900">
                {{ row.label }}
              </label>
              <p class="mt-1 text-xs text-slate-500">{{ row.desc }}</p>
              <p
                v-if="isMissing(row) && row.importance !== 'optional'"
                class="mt-1 text-xs font-medium text-rose-700"
              >
                Без него: {{ row.breaks }}
              </p>
              <p v-else-if="isMissing(row)" class="mt-1 text-xs text-slate-500">
                Без него: {{ row.breaks }}
              </p>
              <p v-else class="mt-1 text-xs text-slate-400">
                Тип поля: {{ row.type }}
              </p>
            </div>

            <div class="min-w-0">
              <select
                :id="selectId(row)"
                class="block w-full"
                :value="mappedValue(row)"
                :disabled="!canEdit || creatingKey === `${block}:${row.key}`"
                :aria-describedby="isBroken(row) ? `${selectId(row)}-error` : undefined"
                @change="event => onSelectChange(row, event)"
              >
                <option value="">— не сопоставлено —</option>
                <optgroup v-if="optionGroups(row).suitable.length" label="Подходящие поля">
                  <option
                    v-for="option in optionGroups(row).suitable"
                    :key="`suitable-${block}-${row.key}-${option.value}`"
                    :value="option.value"
                  >
                    {{ option.label }} ({{ option.type }})
                  </option>
                </optgroup>
                <optgroup v-if="optionGroups(row).other.length" label="Другие поля — тип не совпадает">
                  <option
                    v-for="option in optionGroups(row).other"
                    :key="`other-${block}-${row.key}-${option.value}`"
                    :value="option.value"
                  >
                    {{ option.label }} ({{ option.type }})
                  </option>
                </optgroup>
              </select>

              <p
                v-if="isBroken(row)"
                :id="`${selectId(row)}-error`"
                class="mt-1 text-xs font-medium text-rose-700"
              >
                Поля «{{ mappedValue(row) }}» в смарт-процессе больше нет — выберите другое.
              </p>

              <div v-if="row.creatable" class="mt-2">
                <B24Button
                  label="Создать поле на портале"
                  color="default"
                  size="xs"
                  :loading="creatingKey === `${block}:${row.key}`"
                  :disabled="!canEdit || !status.entityTypeId || Boolean(creatingKey)"
                  @click="emit('create', row.key, row.label)"
                />
                <p class="mt-1 text-xs text-slate-400">
                  Заведёт поле нужного типа в смарт-процессе и сразу привяжет его к этой строке.
                </p>
              </div>
            </div>
          </div>
        </div>
      </details>
    </section>

    <!--
      Справочник полей смарт-процесса.

      Свёрнут: раньше две такие таблицы висели раскрытыми и занимали экран,
      хотя нужны только при разборе «почему нужного поля нет в списке».
    -->
    <details class="rounded-2xl border border-slate-200 bg-white">
      <summary class="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-900">
        Все поля смарт-процесса ({{ spFields.length }})
      </summary>
      <div v-if="spFields.length" class="max-h-72 overflow-y-auto border-t border-slate-100">
        <table class="ms-table">
          <thead class="sticky top-0">
            <tr>
              <th>Название</th>
              <th>Код</th>
              <th>Тип</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="field in spFields" :key="`sp-field-${block}-${field.id}`">
              <td class="font-medium text-slate-900">{{ field.title }}</td>
              <td class="font-mono text-xs text-slate-500">{{ field.id }}</td>
              <td class="text-slate-500">{{ field.type }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="border-t border-slate-100 px-4 py-3 text-sm text-slate-500">
        Поля ещё не загружены.
      </p>
    </details>
  </div>
</template>
