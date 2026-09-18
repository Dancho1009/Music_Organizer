import { FileWarning, ListRestart, Music2, ScanText, Trash2 } from 'lucide-react'
import type { MigrationPlan, TrackPlan } from '../types/plan'

interface PlanListProps {
  plan: MigrationPlan
  decisions: Record<string, Record<string, string | boolean>>
  onIgnoreLyrics(track: TrackPlan): void
  onSelectLyrics(track: TrackPlan): void
  onConfirmLyrics(track: TrackPlan): void
  onDeleteLyrics(track: TrackPlan): void
  onExclude(track: TrackPlan): void
}

function statusText(status: string): string {
  const values: Record<string, string> = {
    ready: '可执行',
    warning: '有提示',
    reuse: '已存在',
    blocked: '已阻断',
    manual_review: '待确认',
    applied: '已执行',
    completed: '已完成'
  }
  return values[status] || status
}

function TrackRow({ track, decisions, onIgnoreLyrics, onSelectLyrics, onConfirmLyrics, onDeleteLyrics, onExclude }: Omit<PlanListProps, 'plan'> & { track: TrackPlan }): JSX.Element {
  const needsLyricsReview = track.issues.some((issue) => issue.code === 'lyrics_requires_review' || issue.code === 'missing_lrc')
  const canConfirmLyrics = track.issues.some((issue) => issue.code === 'lyrics_requires_review')
  const canDeleteLyrics = canConfirmLyrics && track.lyrics.status !== 'actual'
  const canExclude = track.issues.some((issue) => issue.code === 'different_destination_file')
  const decision = decisions[track.track_id]
  return (
    <article className="track-row">
      <div className="track-icon"><Music2 size={18} /></div>
      <div className="track-main">
        <div className="track-title">
          <strong>{track.relative_source}</strong>
          <span className={`state state-${track.status}`}>{statusText(track.status)}</span>
        </div>
        <div className="track-meta">
          <span>{track.audio_format.toUpperCase()}</span>
          <span>{track.resolved.main_artist || '歌词清理'}</span>
          <span>{track.resolved.album || '不迁移音频'}</span>
          <span>歌词：{track.lyrics.status}</span>
        </div>
        {track.lyrics.metadata_samples && track.lyrics.metadata_samples.length > 0 && (
          <div className="lyrics-preview">检测到的内容：{track.lyrics.metadata_samples.join(' / ')}</div>
        )}
        {track.assets[0] && <div className="destination-path">{track.assets[0].destination}</div>}
        {track.issues.map((issue) => (
          <div className={`issue issue-${issue.severity}`} key={`${track.track_id}-${issue.code}`}>
            <FileWarning size={15} />
            <span>{issue.message}</span>
          </div>
        ))}
        {decision && <div className="decision">待重新生成：{decision.exclude ? '排除歌曲' : decision.lyrics_action === 'delete' ? '删除异常歌词' : decision.lyrics_action === 'ignore' ? '忽略歌词' : decision.lyrics_status === 'actual' ? '确认实际歌词' : String(decision.lyrics_path || '')}</div>}
      </div>
      {(needsLyricsReview || canExclude) && (
        <div className="track-actions">
          {needsLyricsReview && <button type="button" onClick={() => onSelectLyrics(track)}><ScanText size={16} />选择歌词</button>}
          {canConfirmLyrics && <button type="button" onClick={() => onConfirmLyrics(track)}><ScanText size={16} />确认为歌词</button>}
          {canDeleteLyrics && <button type="button" onClick={() => onDeleteLyrics(track)}><Trash2 size={16} />删除歌词</button>}
          {needsLyricsReview && <button type="button" onClick={() => onIgnoreLyrics(track)}><ListRestart size={16} />忽略歌词</button>}
          {canExclude && <button type="button" onClick={() => onExclude(track)}><ListRestart size={16} />排除本曲</button>}
        </div>
      )}
    </article>
  )
}

export function PlanList({ plan, decisions, onIgnoreLyrics, onSelectLyrics, onConfirmLyrics, onDeleteLyrics, onExclude }: PlanListProps): JSX.Element {
  return (
    <div className="track-list">
      {plan.tracks.map((track) => (
        <TrackRow
          key={track.track_id}
          track={track}
          decisions={decisions}
          onIgnoreLyrics={onIgnoreLyrics}
          onSelectLyrics={onSelectLyrics}
          onConfirmLyrics={onConfirmLyrics}
          onDeleteLyrics={onDeleteLyrics}
          onExclude={onExclude}
        />
      ))}
    </div>
  )
}
