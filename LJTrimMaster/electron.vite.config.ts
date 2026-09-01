import { resolve } from 'node:path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

const shared = resolve(__dirname, 'shared')
const models = resolve(__dirname, 'renderer/models')

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: { alias: { '@shared': shared, '@models': models } },
    build: {
      outDir: 'out/main',
      lib: { entry: resolve(__dirname, 'main/main.ts') }
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    resolve: { alias: { '@shared': shared } },
    build: {
      outDir: 'out/preload',
      lib: { entry: resolve(__dirname, 'main/preload.ts') }
    }
  },
  renderer: {
    root: resolve(__dirname, 'renderer'),
    plugins: [react()],
    resolve: { alias: { '@shared': shared, '@models': models } },
    build: {
      outDir: 'out/renderer',
      rollupOptions: { input: resolve(__dirname, 'renderer/index.html') }
    }
  }
})
