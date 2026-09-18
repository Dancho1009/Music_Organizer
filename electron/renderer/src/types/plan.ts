export interface AssetPlan {
  kind: 'audio' | 'lrc' | 'cover'
  source: string
  destination: string
  action: 'move' | 'link' | 'reuse' | 'skip'
  status: string
  execution?: { method?: string; sha256?: string }
}

export interface Issue {
  code: string
  severity: 'blocked' | 'manual_review' | 'warning'
  message: string
  candidates?: string[]
}

export interface TrackPlan {
  track_id: string
  source_audio: string
  relative_source: string
  audio_format: string
  tags: Record<string, string | null>
  resolved: Record<string, string>
  lyrics: {
    status: string
    source?: string
    match_type?: string
    actual_samples?: string[]
    metadata_samples?: string[]
    deletion?: { requested?: boolean; state?: string; fingerprint?: Record<string, number | string> }
  }
  assets: AssetPlan[]
  issues: Issue[]
  status: string
}

export interface LyricsDeletionPreview {
  plan_id: string
  applied: boolean
  ok: boolean
  count: number
  deleted: string[]
  blocked: Array<{ source: string; reason?: string }>
  candidates: Array<{ source: string; state: string; ok: boolean; reason?: string }>
  journal_path: string
  report_path?: string
  plan?: MigrationPlan
}

export interface MigrationPlan {
  plan_id: string
  plan_version: number
  parent_plan_id?: string | null
  status: string
  summary: Record<string, number>
  config: {
    source: string
    flac_destination: string | null
    mp3_destination: string | null
    mode: 'move' | 'link'
    lyrics_cleanup_only?: boolean
  }
  tracks: TrackPlan[]
}

export interface PlanHistoryItem {
  plan_id: string
  plan_version: number
  parent_plan_id?: string | null
  status: string
  created_at: string
  plan_path: string
  summary: Record<string, number>
  recovery?: {
    journal_path?: string
    completed_assets: number
    incomplete_assets: unknown[]
    can_resume: boolean
    can_rollback: boolean
    consistency: unknown[]
    pending_consistency: unknown[]
  }
}

export interface Verification {
  ok: boolean
  passed: number
  failed: number
  checks: Array<{ kind: string; source: string; destination: string; ok: boolean }>
}
