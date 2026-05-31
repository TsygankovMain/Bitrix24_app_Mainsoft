import { reactive, computed } from 'vue'

// Module-level singleton: общее состояние прогресса на всё приложение
const state = reactive({
  count: 0,
  title: '',
  done: 0,
  total: 0,
})

export function useProgress() {
  function begin(title = '', total = 0) {
    state.count++
    state.title = title
    state.done = 0
    state.total = total
  }
  function update(done: number, total?: number) {
    state.done = done
    if (total !== undefined) state.total = total
  }
  function end() {
    state.count = Math.max(0, state.count - 1)
    if (state.count === 0) {
      state.title = ''
      state.done = 0
      state.total = 0
    }
  }
  const active = computed(() => state.count > 0)
  return { state, active, begin, update, end }
}
