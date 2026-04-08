// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  {
    files: ['app/utils/**/*.{ts,js}', 'app/composables/**/*.{ts,js}'],
    rules: {
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-alert': 'error',
    },
  },
)
