import { BrowserWindow, Menu, type MenuItemConstructorOptions } from 'electron'
import { IpcChannels } from '@shared/ipcChannels'
import type { MenuCommand } from '@shared/types'

/**
 * The application menu.
 *
 * Replacing Electron's default menu means we own what survives, so this keeps
 * the View roles that make the app debuggable and drops the rest.
 *
 * ## Deliberately no Edit → Undo / Redo
 *
 * Menu accelerators are handled before the renderer sees the keystroke, so a
 * `role: 'undo'` item bound to CmdOrCtrl+Z would swallow the shortcut and run
 * the *text field's* undo instead of the sheet's transform undo. The editor
 * handles Ctrl+Z itself (and steps aside when focus is in an input), and that
 * only keeps working if nothing here claims the accelerator.
 *
 * On Windows and Linux the native clipboard shortcuts work in text fields
 * without menu items. macOS needs an Edit menu with roles for those to bind —
 * worth adding if this is ever built for Mac, minding the note above.
 */
export class AppMenu {
  install(): void {
    Menu.setApplicationMenu(Menu.buildFromTemplate(this.template()))
  }

  private template(): MenuItemConstructorOptions[] {
    const isMac = process.platform === 'darwin'

    return [
      ...(isMac ? ([{ role: 'appMenu' }] as MenuItemConstructorOptions[]) : []),
      {
        label: '&File',
        submenu: [isMac ? { role: 'close' } : { role: 'quit' }]
      },
      {
        label: '&View',
        submenu: [
          { role: 'reload' },
          { role: 'forceReload' },
          { role: 'toggleDevTools' },
          { type: 'separator' },
          { role: 'resetZoom' },
          { role: 'zoomIn' },
          { role: 'zoomOut' },
          { type: 'separator' },
          { role: 'togglefullscreen' }
        ]
      },
      {
        label: '&Help',
        submenu: [
          {
            label: 'How To Use',
            accelerator: 'F1',
            click: () => this.send('howToUse')
          }
        ]
      }
    ]
  }

  /**
   * Menu clicks go to the focused window, falling back to the first one — a
   * menu can be invoked while no window holds focus.
   */
  private send(command: MenuCommand): void {
    const target = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    target?.webContents.send(IpcChannels.MENU_COMMAND, command)
  }
}
