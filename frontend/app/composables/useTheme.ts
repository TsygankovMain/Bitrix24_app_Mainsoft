// frontend/app/composables/useTheme.ts
import { ref, onMounted, watch } from 'vue'

type Theme = 'light' | 'dark' | 'system'

export function useTheme() {
  const theme = ref<Theme>('system')
  const storageKey = 'app-theme'

  const applyTheme = (newTheme: Theme) => {
    const root = document.documentElement
    if (
      newTheme === 'dark' ||
      (newTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    ) {
      root.classList.add('dark')
      root.classList.remove('light')
    } else {
      root.classList.remove('dark')
      root.classList.add('light')
    }
  }

  const setTheme = (newTheme: Theme) => {
    theme.value = newTheme
    localStorage.setItem(storageKey, newTheme)
    applyTheme(newTheme)
  }

  onMounted(() => {
    const savedTheme = localStorage.getItem(storageKey) as Theme | null
    if (savedTheme) {
      theme.value = savedTheme
    }
    applyTheme(theme.value)

    // Listen for system theme changes
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => {
      if (theme.value === 'system') {
        applyTheme('system')
      }
    }
    mediaQuery.addEventListener('change', handleChange)
    
    // Watch for changes in the theme ref and re-apply
    watch(theme, (newTheme) => {
        applyTheme(newTheme)
    })
  })

  return {
    theme,
    setTheme,
  }
}
