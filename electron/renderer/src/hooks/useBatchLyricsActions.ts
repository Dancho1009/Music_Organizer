import type { TrackPlan } from '../types/plan'

type Decisions = Record<string, Record<string, string | boolean>>

export function buildBatchLyricsDecision(
  tracks: TrackPlan[],
  action: 'confirm' | 'ignore' | 'delete'
): Decisions {
  return tracks.reduce<Decisions>((result, track) => {
    result[track.track_id] =
      action === 'confirm'
        ? { lyrics_status: 'actual' }
        : { lyrics_action: action === 'ignore' ? 'ignore' : 'delete' }
    return result
  }, {})
}

export function mergeDecisions(
  current: Decisions,
  next: Decisions
): Decisions {
  return {
    ...current,
    ...next
  }
}
