import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import path from 'node:path'
import { type EngineArgs, type EngineCommand, runEngine } from './engine'

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 680,
    show: false,
    backgroundColor: '#f5f6f8',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }
}

function installIpc(): void {
  ipcMain.handle('music:choose-directory', async () => {
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: '选择目录',
      properties: ['openDirectory', 'createDirectory']
    })
    return result.canceled ? null : result.filePaths[0]
  })
  ipcMain.handle('music:choose-lrc', async () => {
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: '选择歌词文件',
      filters: [{ name: 'LRC 歌词', extensions: ['lrc'] }],
      properties: ['openFile']
    })
    return result.canceled ? null : result.filePaths[0]
  })
  ipcMain.handle('music:open-path', async (_event, targetPath: string) => {
    if (!targetPath) return false
    shell.showItemInFolder(targetPath)
    return true
  })
  ipcMain.handle('music:open-file', async (_event, targetPath: string) => {
    if (!targetPath) return false
    await shell.openPath(targetPath)
    return true
  })
  ipcMain.handle(
    'music:run-engine',
    async (event, request: { command: EngineCommand; args: EngineArgs }) => {
      return runEngine(request.command, request.args, (progress) => {
        if (!progress || typeof progress !== 'object' || (progress as { event?: string }).event !== 'result') {
          event.sender.send('music:progress', progress)
        }
      })
    }
  )
}

app.whenReady().then(() => {
  installIpc()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
