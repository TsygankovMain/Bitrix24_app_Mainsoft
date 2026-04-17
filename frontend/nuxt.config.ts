import tailwindcss from '@tailwindcss/vite'
import { contentLocales } from './i18n/i18n.map'

export default defineNuxtConfig({
  modules: [
    '@bitrix24/b24ui-nuxt',
    '@bitrix24/b24jssdk-nuxt',
    '@nuxt/eslint',
    '@nuxtjs/i18n',
    '@pinia/nuxt'
  ],

  ssr: false,

  devtools: { enabled: false },

  runtimeConfig: {
    /**
     * @memo this will be overwritten from .env or Docker_*
     * @see https://nuxt.com/docs/guide/going-further/runtime-config#example
     */
    public: {
      appUrl: '',
      apiUrl: ''
    }
  },

  compatibilityDate: '2025-07-16',

  experimental: {
    asyncEntry: false
  },

  app: {
    head: {
      title: 'Starter',
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200' }
      ],
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' }
      ],
      htmlAttrs: { class: 'light' }
    }
  },

  css: ['~/assets/css/main.css'],

  vite: {
    plugins: [
      {
        name: 'mainsoft-fs-entry-rewrite',
        transformIndexHtml(html) {
          return html.replaceAll('/_nuxt/Users/', '/_nuxt/@fs/Users/')
        },
        configureServer(server) {
          const rewriteFsEntry = (req: any, _res: any, next: () => void) => {
            const url = req.url || ''
            if (url.startsWith('/_nuxt/Users/')) {
              req.url = url.replace('/_nuxt/Users/', '/_nuxt/@fs/Users/')
            }
            next()
          }

          // Place rewrite before Vite static middlewares.
          // Nuxt dev may emit module URLs like "/_nuxt/Users/.../entry.async.js"
          // and Vite only serves them correctly via "/_nuxt/@fs/Users/...".
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ;(server.middlewares as any).stack.unshift({
            route: '',
            handle: rewriteFsEntry
          })
        },
      },
      tailwindcss()
    ],
    build: {
      target: 'es2020', // Change target to support modern destructuring syntax
      minify: true
    },
    server: {
      allowedHosts: [
        'localhost',
        '127.0.0.1',
        'wanly-evolved-lionfish.cloudpub.ru'
      ],
      proxy: {
        '/api': { target: process.env.SERVER_HOST || 'http://api-need_set:8000', changeOrigin: true }
      }
    }
  },

  nitro: {
    devProxy: {
      '/api': { target: process.env.SERVER_HOST || 'http://api-need_set:8000', changeOrigin: true }
    },
  },

  i18n: {
    detectBrowserLanguage: false,
    strategy: 'no_prefix',
    langDir: 'locales',
    locales: contentLocales,
    defaultLocale: 'en'
  }
})
