<script setup lang="ts">
defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <B24Slideover
    :open="modelValue"
    side="right"
    title="Инструкция: Учёт времени"
    @update:open="(val) => emit('update:modelValue', val)"
  >
    <template #body>
      <div class="space-y-8">
        <!-- 1. Интерфейс -->
        <section class="space-y-2">
          <h3 class="text-xl font-bold text-slate-900">1. Интерфейс вкладки</h3>
          <p class="text-sm text-slate-600">
            Вкладка <strong>«Учёт часов»</strong> показывает структуру подзадач и позволяет вносить время.
          </p>

          <div class="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center">
            <div class="mb-2 text-2xl">📸</div>
            <p class="text-xs font-medium text-slate-500">Скриншот общего вида</p>
          </div>

          <ul class="ml-2 list-disc list-inside space-y-1 text-sm text-slate-600">
            <li><strong>Дерево задач:</strong> Текущая задача и подзадачи.</li>
            <li><strong>Часы:</strong> План / Факт справа от каждой задачи.</li>
            <li><strong>Итоги:</strong> Внизу суммарное время.</li>
          </ul>
        </section>

        <!-- 2. Добавление записи -->
        <section class="space-y-2">
          <h3 class="text-xl font-bold text-slate-900">2. Как внести время</h3>
          <ol class="ml-2 list-decimal list-inside space-y-1 text-sm text-slate-600">
            <li>Нажмите <strong>«Отразить»</strong> (синий плюс).</li>
            <li>Заполните поля:
              <ul class="ml-4 mt-1 list-disc list-inside text-slate-500">
                <li><strong>Описание:</strong> Что сделано.</li>
                <li><strong>Часы:</strong> Затраченное время.</li>
                <li><strong>Учитывать:</strong> Галочка (влияет на отчеты).</li>
              </ul>
            </li>
            <li>Нажмите <strong>«Сохранить»</strong>.</li>
          </ol>

          <div class="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center">
            <div class="mb-2 text-2xl">📸</div>
            <p class="text-xs font-medium text-slate-500">Скриншот формы добавления</p>
          </div>
        </section>

        <!-- 3. Разделение записи -->
        <section class="space-y-2">
          <h3 class="text-xl font-bold text-slate-900">3. Разделение записи (Split)</h3>
          <p class="text-sm text-slate-600">
            Если нужно разделить запись (частично оплачивается/нет):
          </p>
          <ol class="ml-2 list-decimal list-inside space-y-1 text-sm text-slate-600">
            <li>Нажмите на запись в списке.</li>
            <li>В блоке <strong>«Разделение (Split)»</strong> введите часы для отделения.</li>
            <li>Выберите «Учитывать?».</li>
            <li>Нажмите <strong>«Разделить»</strong>.</li>
          </ol>

          <div class="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center">
            <div class="mb-2 text-2xl">📸</div>
            <p class="text-xs font-medium text-slate-500">Скриншот блока Split</p>
          </div>

          <div class="rounded-r-xl border-l-4 border-[#0075ff] bg-blue-50 p-3">
            <p class="text-xs text-slate-700">
              Старая запись уменьшится, появится новая. Общая сумма не изменится.
            </p>
          </div>
        </section>
      </div>
    </template>

    <template #footer>
      <B24Button label="Закрыть инструкцию" color="primary" @click="close" />
    </template>
  </B24Slideover>
</template>
