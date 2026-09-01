import { app, BrowserWindow, protocol, net } from 'electron'
import { join, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'
import { EventBus } from '@shared/events/EventBus'
import { registerIpc } from './ipc'

/**
 * App bootstrap: one window, one main-process EventBus, and the ljtm://
 * protocol the Viewport and Assets panel use to display source textures.
 */

const bus = new EventBus()

/**
 * Where maps.yaml and preset-packs/ live — "next to the binary".
 * Packaged, that is the folder containing the executable. In dev, the app root.
 */
function resolveBinDir(): string {
  return app.isPackaged ? dirname(app.getPath('exe')) : app.getAppPath()
}

/**
 * The renderer can't read image_dump/ directly with contextIsolation on, and
 * shipping every thumbnail through IPC as a data URL would be wasteful. A
 * custom protocol lets <img src> stream straight off disk instead:
 *   ljtm://local/<url-encoded absolute path>
 */
function registerAssetProtocol(): void {
  protocol.handle('ljtm', (request) => {
    const url = new URL(request.url)
    const filePath = decodeURIComponent(url.pathname).replace(/^\/+/, '')
    if (!filePath) return new Response('Bad path', { status: 400 })
    return net.fetch(pathToFileURL(filePath).toString())
  })
}

// Must be called before app is ready.
protocol.registerSchemesAsPrivileged([
  { scheme: 'ljtm', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }
])

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1600,
    height: 1000,
    // The two-column sidebar is a fixed 560px; this leaves the Viewport a
    // usable ~720px at the narrowest the window can go.
    minWidth: 1280,
    minHeight: 700,
    backgroundColor: '#1b1b1f',
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  win.once('ready-to-show', () => win.show())

  const devServerUrl = process.env.ELECTRON_RENDERER_URL
  if (devServerUrl) {
    void win.loadURL(devServerUrl)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

void app.whenReady().then(() => {
  registerAssetProtocol()
  registerIpc(bus, resolveBinDir())
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
