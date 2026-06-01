<script setup lang="ts">
const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

function handleUpdateOpen(value: boolean) {
  if (!value) emit('close')
}
</script>

<template>
  <B24Modal
    :open="open"
    title="Как работать с модулем «Учет часов»"
    @update:open="handleUpdateOpen"
  >
    <template #body>
      <div class="space-y-4 text-sm text-slate-500">
        <p>Этот модуль позволяет учитывать затраченное время на задачу и её подзадачи.</p>

        <h4 class="font-bold text-slate-700">1. Обзор ситуации</h4>
        <ul class="list-disc pl-5 space-y-1">
          <li><strong>Сводка сверху:</strong> Показывает общее время, оплачиваемое (для клиента) и внутреннее.</li>
          <li><strong>Дерево задач:</strong> Вы видите текущую задачу и все вложенные подзадачи с итогами по каждой.</li>
        </ul>

        <h4 class="font-bold text-slate-700">2. Добавление и редактирование</h4>
        <ul class="list-disc pl-5 space-y-1">
          <li>Нажмите <strong>(+)</strong> напротив задачи, чтобы добавить часы.</li>
          <li>Кликните на существующую запись, чтобы <strong>изменить</strong> часы, комментарий или дату.</li>
        </ul>

        <h4 class="font-bold text-slate-700">3. Статусы (Billable)</h4>
        <p>Используйте переключатель, чтобы отметить часы как <strong>Оплачиваемые</strong> (зеленый) или <strong>Внутренние</strong> (серый).</p>

        <h4 class="font-bold text-slate-700">4. Отчеты</h4>
        <p>Кнопка <strong>«В отчет»</strong> перенесет все оплачиваемые часы в стандартный отчет Битрикс24 (Elapsed Time) для биллинга.</p>
      </div>
    </template>

    <template #footer>
      <B24Button label="Понятно" color="primary" @click="emit('close')" />
    </template>
  </B24Modal>
</template>
