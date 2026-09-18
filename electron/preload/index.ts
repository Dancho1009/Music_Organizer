import { contextBridge, ipcRenderer } from 'electron'
import type { EngineArgs, EngineCommand } from '../main/engine'

const api = {
  chooseDirectory: (): Promise<string | null> => ipcRenderer.invoke('music:choose-directory'),
  chooseLrc: (): Promise<string | null> => ipcRenderer.invoke('music:choose-lrc'),
  runEngine: (command: EngineCommand, args: EngineArgs) =>
    ipcRenderer.invoke('music:run-engine', { command, args }),
  onProgress: (listener: (event: unknown) => void): (() => void) => {
    const handler = (_: Electron.IpcRendererEvent, event: unknown): void => listener(event)
    ipcRenderer.on('music:progress', handler)
    return () => ipcRenderer.removeListener('music:progress', handler)
  }
}

contextBridge.exposeInMainWorld('musicOrganizer', api)
