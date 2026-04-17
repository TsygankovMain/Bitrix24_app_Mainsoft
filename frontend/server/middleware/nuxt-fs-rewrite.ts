export default defineEventHandler((event) => {
  const currentUrl = event.node.req.url || ''
  if (!currentUrl.startsWith('/_nuxt/Users/')) {
    return
  }

  setHeader(event, 'x-mainsoft-rewrite-hit', '1')
  event.node.req.url = currentUrl.replace('/_nuxt/Users/', '/_nuxt/@fs/Users/')
})
