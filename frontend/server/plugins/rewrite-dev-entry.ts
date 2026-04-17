export default defineNitroPlugin((nitroApp) => {
  nitroApp.hooks.hook('render:response', (response, { event }) => {
    if (process.env.NODE_ENV !== 'development') {
      return
    }

    const body = response.body
    if (typeof body !== 'string' || !body.includes('/_nuxt/Users/')) {
      return
    }

    const reqUrl = event.node.req.url || ''
    response.body = body.replaceAll('/_nuxt/Users/', '/_nuxt/@fs/Users/')

    // Dev-only trace to verify rewrite in browser DevTools response headers.
    response.headers = response.headers || {}
    response.headers['x-mainsoft-entry-rewrite'] = `1:${reqUrl}`
  })
})
