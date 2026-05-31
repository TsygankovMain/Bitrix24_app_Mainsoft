import { reactive, computed } from 'vue'

// Module-level singleton: общее состояние прогресса на всё приложение
const state = reactive({
  count: 0,
  title: '',
  hint: '',
  done: 0,
  total: 0,
})

export function useProgress() {
  function begin(title = '', total = 0, hint = '') {
    state.count++
    state.title = title
    state.hint = hint
    state.done = 0
    state.total = total
  }
  function update(done: number, total?: number) {
    state.done = done
    if (total !== undefined) state.total = total
  }
  // Сменить надпись/подсказку этапа внутри уже идущей операции (счётчик и режим полосы не трогаем)
  function stage(title: string, hint?: string) {
    state.title = title
    if (hint !== undefined) state.hint = hint
  }
  function end() {
    state.count = Math.max(0, state.count - 1)
    if (state.count === 0) {
      state.title = ''
      state.hint = ''
      state.done = 0
      state.total = 0
    }
  }
  const active = computed(() => state.count > 0)
  return { state, active, begin, update, stage, end }
}
