<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { DateTime } from 'luxon'

const props = defineProps<{
  modelValue: string        // YYYY-MM-DD
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const isOpen = ref(false)
const pickerRef = ref<HTMLElement | null>(null)
const viewMonth = ref(DateTime.now().startOf('month'))

const selectedDate = computed(() => {
  if (!props.modelValue) return null
  const d = DateTime.fromISO(props.modelValue)
  return d.isValid ? d.startOf('day') : null
})

const displayText = computed(() => {
  if (!selectedDate.value) return ''
  return selectedDate.value.setLocale('ru').toFormat('d MMMM yyyy')
})

const monthLabel = computed(() =>
  viewMonth.value.setLocale('ru').toFormat('LLLL yyyy')
)

// Build 6-week calendar grid starting from Monday
const calendarDays = computed(() => {
  const start = viewMonth.value.startOf('month').startOf('week')
  const end = viewMonth.value.endOf('month').endOf('week')
  const days: DateTime[] = []
  let cur = start
  while (cur <= end) {
    days.push(cur)
    cur = cur.plus({ days: 1 })
  }
  return days
})

const weekDays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function openPicker() {
  if (selectedDate.value) viewMonth.value = selectedDate.value.startOf('month')
  isOpen.value = true
}

function selectDay(day: DateTime) {
  emit('update:modelValue', day.toFormat('yyyy-MM-dd'))
  isOpen.value = false
}

function clearValue() {
  emit('update:modelValue', '')
}

function prevMonth() { viewMonth.value = viewMonth.value.minus({ months: 1 }) }
function nextMonth() { viewMonth.value = viewMonth.value.plus({ months: 1 }) }

function isSelected(d: DateTime) { return selectedDate.value ? d.hasSame(selectedDate.value, 'day') : false }
function isToday(d: DateTime) { return d.hasSame(DateTime.now(), 'day') }
function isCurrentMonth(d: DateTime) { return d.hasSame(viewMonth.value, 'month') }
function isWeekend(d: DateTime) { return d.weekday >= 6 }

function handleOutsideClick(e: MouseEvent) {
  if (pickerRef.value && !pickerRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', handleOutsideClick))
onUnmounted(() => document.removeEventListener('mousedown', handleOutsideClick))
</script>

<template>
  <div class="dp-wrapper" ref="pickerRef">
    <!-- Trigger -->
    <div class="dp-trigger" :class="{ 'dp-open': isOpen, 'dp-filled': !!modelValue }" @click="openPicker">
      <svg class="dp-cal-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd" />
      </svg>
      <span class="dp-value" :class="{ 'dp-placeholder': !modelValue }">
        {{ displayText || placeholder || 'Выберите дату' }}
      </span>
      <button v-if="modelValue" class="dp-clear" @click.stop="clearValue" title="Очистить">
        <svg viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
        </svg>
      </button>
      <svg class="dp-chevron" :class="{ 'dp-chevron-up': isOpen }" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    </div>

    <!-- Dropdown Calendar -->
    <Transition name="dp-fade">
      <div v-if="isOpen" class="dp-dropdown">
        <!-- Month navigation -->
        <div class="dp-header">
          <button class="dp-nav-btn" @click="prevMonth">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
          </button>
          <span class="dp-month-label">{{ monthLabel }}</span>
          <button class="dp-nav-btn" @click="nextMonth">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"/></svg>
          </button>
        </div>

        <!-- Weekday headers -->
        <div class="dp-weekdays">
          <div v-for="wd in weekDays" :key="wd" class="dp-wd">{{ wd }}</div>
        </div>

        <!-- Days -->
        <div class="dp-days">
          <button
            v-for="day in calendarDays"
            :key="day.toISO() ?? day.toMillis()"
            class="dp-day"
            :class="{
              'dp-day-selected': isSelected(day),
              'dp-day-today': isToday(day),
              'dp-day-outside': !isCurrentMonth(day),
              'dp-day-weekend': isWeekend(day),
            }"
            @click="selectDay(day)"
          >{{ day.day }}</button>
        </div>

        <!-- Footer shortcuts -->
        <div class="dp-footer">
          <button class="dp-today-btn" @click="selectDay(DateTime.now())">Сегодня</button>
          <button class="dp-clear-btn" @click="clearValue">Очистить</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ====== Trigger ====== */
.dp-wrapper {
  position: relative;
  display: inline-block;
  min-width: 180px;
}

.dp-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
  user-select: none;
  min-height: 38px;
}

.dp-trigger:hover {
  border-color: #93c5fd;
}

.dp-trigger.dp-open {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.dp-cal-icon {
  width: 16px;
  height: 16px;
  color: #6b7280;
  flex-shrink: 0;
}

.dp-value {
  flex: 1;
  font-size: 14px;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dp-placeholder {
  color: #9ca3af;
}

.dp-clear {
  display: flex;
  align-items: center;
  padding: 2px;
  border: none;
  background: none;
  color: #9ca3af;
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
}

.dp-clear:hover { color: #374151; background: #f3f4f6; }
.dp-clear svg { width: 12px; height: 12px; }

.dp-chevron {
  width: 14px;
  height: 14px;
  color: #9ca3af;
  flex-shrink: 0;
  transition: transform 0.2s;
}

.dp-chevron-up { transform: rotate(180deg); }

/* ====== Dropdown ====== */
.dp-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 1000;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 10px 25px -5px rgba(0,0,0,0.12), 0 4px 10px -3px rgba(0,0,0,0.08);
  padding: 12px;
  min-width: 280px;
}

/* ====== Header ====== */
.dp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.dp-nav-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  border-radius: 6px;
  cursor: pointer;
  color: #6b7280;
  transition: background 0.15s, color 0.15s;
}

.dp-nav-btn:hover { background: #f3f4f6; color: #111827; }
.dp-nav-btn svg { width: 16px; height: 16px; }

.dp-month-label {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  text-transform: capitalize;
}

/* ====== Weekdays ====== */
.dp-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 4px;
}

.dp-wd {
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  padding: 4px 0;
}

/* ====== Days ====== */
.dp-days {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}

.dp-day {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: none;
  border-radius: 8px;
  font-size: 13px;
  color: #374151;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
  font-weight: 400;
}

.dp-day:hover:not(.dp-day-selected) {
  background: #eff6ff;
  color: #1d4ed8;
}

.dp-day-selected {
  background: #3b82f6;
  color: #fff;
  font-weight: 600;
}

.dp-day-today:not(.dp-day-selected) {
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
}

.dp-day-outside {
  color: #d1d5db;
}

.dp-day-outside:hover:not(.dp-day-selected) {
  background: #f9fafb;
  color: #9ca3af;
}

.dp-day-weekend:not(.dp-day-selected):not(.dp-day-today) {
  color: #ef4444;
}

.dp-day-outside.dp-day-weekend { color: #fca5a5; }

/* ====== Footer ====== */
.dp-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f3f4f6;
}

.dp-today-btn, .dp-clear-btn {
  background: none;
  border: none;
  font-size: 12px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s;
  font-weight: 500;
}

.dp-today-btn { color: #3b82f6; }
.dp-today-btn:hover { background: #eff6ff; }
.dp-clear-btn { color: #6b7280; }
.dp-clear-btn:hover { background: #f3f4f6; }

/* ====== Animation ====== */
.dp-fade-enter-active, .dp-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dp-fade-enter-from, .dp-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}
</style>
