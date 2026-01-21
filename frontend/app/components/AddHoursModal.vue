<script setup lang="ts">
import { ref, watch, computed } from 'vue'

const props = defineProps<{
  open: boolean
  taskId?: string // ID of task we are adding to
  taskTitle?: string
  editItem?: any // If editing, pass item here
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', data: any): void
}>()

const form = ref({
  hours: '',
  description: '',
  date: new Date().toISOString().split('T')[0],
  isBillable: true
})

// Reset or Fill form on open
watch(() => props.open, (newVal) => {
  if (newVal) {
    if (props.editItem) {
      form.value = {
        hours: props.editItem.hours.toString(),
        description: props.editItem.description,
        date: props.editItem.date ? new Date(props.editItem.date).toISOString().split('T')[0] : new Date().toISOString().split('T')[0],
        isBillable: props.editItem.isBillable
      }
    } else {
      form.value = {
        hours: '',
        description: '',
        date: new Date().toISOString().split('T')[0],
        isBillable: true
      }
    }
  }
})

const isValid = computed(() => {
  return form.value.hours && !isNaN(parseFloat(form.value.hours)) && form.value.description.trim().length > 0
})

const onSave = () => {
  if (!isValid.value) return
  emit('save', {
    ...form.value,
    hours: parseFloat(form.value.hours),
    id: props.editItem?.id
  })
}
</script>

<template>
  <div v-if="open" class="relative z-50" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" @click="emit('close')"></div>

    <div class="fixed inset-0 z-10 overflow-y-auto">
      <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div class="relative transform overflow-hidden rounded-lg bg-white px-4 pb-4 pt-5 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:p-6">
          <div class="absolute right-0 top-0 hidden pr-4 pt-4 sm:block">
            <button type="button" class="rounded-md bg-white text-gray-400 hover:text-gray-500 focus:outline-none" @click="emit('close')">
              <span class="sr-only">Close</span>
              <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          <div class="sm:flex sm:items-start">
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left w-full">
              <h3 class="text-base font-semibold leading-6 text-gray-900" id="modal-title">
                {{ editItem ? 'Редактировать запись' : 'Добавить часы' }}
              </h3>
              <div class="mt-2 text-sm text-gray-500" v-if="taskTitle">
                Задача: {{ taskTitle }}
              </div>

              <div class="mt-4 space-y-4">
                <!-- Hours -->
                <div>
                  <label for="hours" class="block text-sm font-medium leading-6 text-gray-900">Количество часов <span class="text-red-500">*</span></label>
                  <div class="mt-1">
                    <input type="number" step="0.5" v-model="form.hours" id="hours" class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6" placeholder="0.0">
                  </div>
                </div>

                <!-- Description -->
                <div>
                  <label for="description" class="block text-sm font-medium leading-6 text-gray-900">Комментарий <span class="text-red-500">*</span></label>
                  <div class="mt-1">
                    <textarea v-model="form.description" id="description" rows="3" class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6" placeholder="Что было сделано..."></textarea>
                  </div>
                </div>

                <!-- Date -->
                <div>
                  <label for="date" class="block text-sm font-medium leading-6 text-gray-900">Дата</label>
                  <div class="mt-1">
                    <input type="date" v-model="form.date" id="date" class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm sm:leading-6">
                  </div>
                </div>

                <!-- Billable Toggle -->
                <div class="relative flex items-start">
                  <div class="flex h-6 items-center">
                    <input id="isBillable" v-model="form.isBillable" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-600">
                  </div>
                  <div class="ml-3 text-sm leading-6">
                    <label for="isBillable" class="font-medium text-gray-900">Оплачиваемое время</label>
                    <p class="text-gray-500">Учитывать часы в счете клиенту</p>
                  </div>
                </div>
              </div>

            </div>
          </div>
          
          <div class="mt-5 sm:mt-6 sm:grid sm:grid-flow-row-dense sm:grid-cols-2 sm:gap-3">
            <button type="button" class="inline-flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 sm:col-start-2 disabled:opacity-50 disabled:cursor-not-allowed" 
              @click="onSave" :disabled="!isValid">
              Сохранить
            </button>
            <button type="button" class="mt-3 inline-flex w-full justify-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 sm:col-start-1 sm:mt-0" @click="emit('close')">
              Отмена
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
