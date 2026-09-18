import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

export default defineConfig({
  main: {
    build: {
      rollupOptions: {
        input: resolve('electron/main/index.ts')
      }
    }
  },
  preload: {
    build: {
      rollupOptions: {
        input: resolve('electron/preload/index.ts')
      }
    }
  },
  renderer: {
    root: resolve('electron/renderer'),
    build: {
      rollupOptions: {
        input: resolve('electron/renderer/index.html')
      }
    },
    plugins: [react()]
  }
})
