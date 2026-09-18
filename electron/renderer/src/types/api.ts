export type EngineCommand = 'plan' | 'apply' | 'rollback' | 'verify' | 'recover' | 'resume' | 'cleanup' | 'delete-lyrics' | 'history'
export type EngineArgs = Record<string, string | boolean | undefined>

export interface EngineResponse {
  events: unknown[]
  result: unknown
}

declare global {
  interface Window {
    musicOrganizer: {
      chooseDirectory(): Promise<string | null>
      chooseLrc(): Promise<string | null>
      openPath(targetPath: string): Promise<boolean>
      openFile(targetPath: string): Promise<boolean>
      runEngine(command: EngineCommand, args: EngineArgs): Promise<EngineResponse>
      onProgress(listener: (event: unknown) => void): () => void
    }
  }
}
