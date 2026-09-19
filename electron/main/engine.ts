import { app } from 'electron'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

export type EngineCommand = 'plan' | 'apply' | 'rollback' | 'verify' | 'recover' | 'resume' | 'cleanup' | 'delete-lyrics' | 'history'
export type EngineArgs = Record<string, string | boolean | undefined>

const allowedArguments: Record<EngineCommand, Set<string>> = {
  plan: new Set(['source', 'flac-destination', 'mp3-destination', 'mode', 'decisions', 'parent-plan', 'lyrics-cleanup-only']),
  apply: new Set(['plan', 'track-ids']),
  rollback: new Set(['plan']),
  verify: new Set(['plan']),
  recover: new Set(['plan']),
  resume: new Set(['plan']),
  cleanup: new Set(['plan', 'apply', 'include-root']),
  'delete-lyrics': new Set(['plan', 'apply']),
  history: new Set()
}

function projectRoot(): string {
  return app.isPackaged ? path.join(process.resourcesPath, 'app') : path.resolve(__dirname, '../..')
}

function dataRoot(): string {
  return path.join(app.getPath('userData'), 'migration-data')
}

function cliArguments(command: EngineCommand, values: EngineArgs): string[] {
  const permitted = allowedArguments[command]
  if (!permitted) throw new Error(`Unsupported engine command: ${String(command)}`)
  const args: string[] = ['-m', 'music_organizer', command]
  for (const [key, value] of Object.entries(values)) {
    if (!permitted.has(key) || value === undefined || value === false) continue
    const flag = `--${key}`
    args.push(flag)
    if (value !== true) args.push(String(value))
  }
  args.push('--data-root', dataRoot())
  return args
}

function prepareDecisions(values: EngineArgs): { args: EngineArgs; cleanup: () => void } {
  const decisions = values.decisions
  if (typeof decisions !== 'string' || !decisions.trim()) {
    return { args: values, cleanup: () => undefined }
  }
  const directory = mkdtempSync(path.join(tmpdir(), 'music-organizer-decisions-'))
  const file = path.join(directory, 'decisions.json')
  writeFileSync(file, decisions, 'utf8')
  return {
    args: { ...values, decisions: file },
    cleanup: () => rmSync(directory, { force: true, recursive: true })
  }
}

export class EngineCommandError extends Error {
  constructor(
    message: string,
    public readonly events: unknown[],
    public readonly exitCode: number | null
  ) {
    super(message)
  }
}

export async function runEngine(
  command: EngineCommand,
  values: EngineArgs,
  onEvent: (event: unknown) => void
): Promise<{ events: unknown[]; result: unknown }> {
  const engineRoot = path.join(projectRoot(), 'engine')
  const python = process.env.MUSIC_ORGANIZER_PYTHON || 'python'
  const prepared = prepareDecisions(values)
  const child = spawn(python, cliArguments(command, prepared.args), {
    cwd: projectRoot(),
    env: {
      ...process.env,
      PYTHONPATH: [engineRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      PYTHONIOENCODING: 'utf-8'
    },
    windowsHide: true
  })
  const events: unknown[] = []
  let stderr = ''
  let pending = ''

  child.stdout.setEncoding('utf8')
  child.stdout.on('data', (chunk: string) => {
    pending += chunk
    const lines = pending.split(/\r?\n/)
    pending = lines.pop() || ''
    for (const line of lines) {
      if (!line.trim()) continue
      try {
        const event = JSON.parse(line)
        events.push(event)
        onEvent(event)
      } catch {
        events.push({ event: 'engine_output', text: line })
      }
    }
  })
  child.stderr.setEncoding('utf8')
  child.stderr.on('data', (chunk: string) => {
    stderr += chunk
  })

  return await new Promise((resolve, reject) => {
    child.once('error', (error) => {
      prepared.cleanup()
      reject(new EngineCommandError(error.message, events, null))
    })
    child.once('close', (code) => {
      prepared.cleanup()
      if (pending.trim()) {
        try {
          const event = JSON.parse(pending)
          events.push(event)
          onEvent(event)
        } catch {
          events.push({ event: 'engine_output', text: pending })
        }
      }
      const finalEvent = events.at(-1) as { result?: unknown; error?: string } | undefined
      if (code === 0) {
        resolve({ events, result: finalEvent?.result ?? finalEvent })
        return
      }
      reject(
        new EngineCommandError(
          finalEvent?.error || stderr.trim() || `Engine exited with code ${code}`,
          events,
          code
        )
      )
    })
  })
}
