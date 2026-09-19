import { FileWarning, FolderOpen, ListRestart, Music2, ScanText, Trash2 } from 'lucide-react'
import type { LyricsReason, MigrationPlan, TrackPlan } from '../types/plan'

interface PlanListProps {
  plan: MigrationPlan
  decisions: Record<string, Record<string, string | boolean>>
  selectedTracks: Set<string>
  onToggleSelect(track: TrackPlan): void
  onOpenFolder(track: TrackPlan): void
  onOpenLyrics(track: TrackPlan): void
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
    suspect: '可疑，需确认',
    malformed: '格式异常',
    applied: '已执行',
    completed: '已完成'
  }
  return values[status] || status
}

function reasonMessage(reason: LyricsReason | string): string {
  return typeof reason === 'string' ? reason : reason.message
}

const HIDDEN_REASON_CODES = new Set(['title_metadata_missing', 'artist_metadata_missing'])

function visibleLyricsReasons(reasons: Array<LyricsReason | string> | undefined): Array<LyricsReason | string> {
  return (reasons || []).filter((reason) => typeof reason === 'string' || !HIDDEN_REASON_CODES.has(reason.code))
}

function TrackRow({ track, decisions, selectedTracks, onToggleSelect, onOpenFolder, onOpenLyrics, onIgnoreLyrics, onSelectLyrics, onConfirmLyrics, onDeleteLyrics, onExclude }: Omit<PlanListProps, 'plan'> & { track: TrackPlan }): JSX.Element {
  const needsLyricsReview = track.issues.some((issue) => issue.code === 'lyrics_requires_review' || issue.code === 'missing_lrc')
  const canConfirmLyrics = track.issues.some((issue) => issue.code === 'lyrics_requires_review')
  const canDeleteLyrics = canConfirmLyrics && track.lyrics.status !== 'actual'
  const canExclude = track.issues.some((issue) => issue.code === 'different_destination_file')
  const decision = decisions[track.track_id]
  const hasLyricsFile = Boolean(track.lyrics.source || decision?.lyrics_path)

  return (
    <article className="track-row">
      <div className="track-icon">
        <input
          type="checkbox"
          checked={selectedTracks.has(track.track_id)}
          onChange={() => onToggleSelect(track)}
          aria-label={`选择 ${track.relative_source}`}
        />
        <Music2 size={18} />
      </div>
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
          {typeof track.lyrics.confidence === 'number' && <span>可信度：{Math.round(track.lyrics.confidence * 100)}%</span>}
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
        {track.lyrics.confidence_version && <div className="lyrics-preview">评分模型：{track.lyrics.confidence_version}</div>}
        {track.lyrics.scores && <div className="lyrics-preview">分项：{Object.entries(track.lyrics.scores).map(([key, value]) => `${key} ${Math.round(value * 100)}%`).join(' · ')}</div>}
        {visibleLyricsReasons(track.lyrics.reasons).map((reason, index) => (
          <div className="lyrics-preview" key={`${track.track_id}-reason-${typeof reason === 'string' ? index : reason.code}`}>
            判定说明：{reasonMessage(reason)}
          </div>
        ))}
        {decision && <div className="decision">待重新生成：{decision.exclude ? '排除歌曲' : decision.lyrics_action === 'delete' ? '删除异常歌词' : decision.lyrics_action === 'ignore' ? '忽略歌词' : decision.lyrics_status === 'actual' ? '确认实际歌词' : String(decision.lyrics_path || '')}</div>}
      </div>
      <div className="track-actions">
        <button type="button" onClick={() => onOpenFolder(track)}><FolderOpen size={16} />打开文件夹</button>
        {hasLyricsFile && <button type="button" onClick={() => onOpenLyrics(track)}><FileWarning size={16} />打开歌词</button>}
        {needsLyricsReview && <button type="button" onClick={() => onSelectLyrics(track)}><ScanText size={16} />选择歌词</button>}
        {canConfirmLyrics && <button type="button" onClick={() => onConfirmLyrics(track)}><ScanText size={16} />确认为歌词</button>}
        {canDeleteLyrics && <button type="button" onClick={() => onDeleteLyrics(track)}><Trash2 size={16} />删除歌词</button>}
        {needsLyricsReview && <button type="button" onClick={() => onIgnoreLyrics(track)}><ListRestart size={16} />忽略歌词</button>}
        {canExclude && <button type="button" onClick={() => onExclude(track)}><ListRestart size={16} />排除本曲</button>}
      </div>
    </article>
  )
}

export function PlanList(props: PlanListProps): JSX.Element {
  return (
    <div className="track-list">
      {props.plan.tracks.map((track) => (
        <TrackRow key={track.track_id} {...props} track={track} />
      ))}
    </div>
  )
}
