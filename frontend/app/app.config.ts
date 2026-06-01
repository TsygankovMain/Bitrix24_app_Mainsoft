export default defineAppConfig({
  // Глобальное уплотнение B24 UI Kit («Air» по умолчанию слишком воздушный):
  // меньше внутренних паддингов карточек, меньше вертикали у шапок,
  // меньше гэпов в гридах и межсекционных отступов.
  b24ui: {
    card: {
      slots: {
        body: 'p-4 sm:p-4',
        header: 'px-4 py-3 sm:px-4 sm:py-3',
        footer: 'px-4 py-3 sm:px-4 sm:py-3'
      }
    },
    pageHeader: {
      slots: {
        root: 'py-4'
      }
    },
    pageGrid: { base: 'gap-4' },
    pageColumns: { base: 'gap-6' },
    pageBody: { base: 'mt-4 space-y-6 pb-8' }
  },
  colorMode: false,
  colorModeTypeLight: 'light' as const // edge-dark | edge-light | light
})
