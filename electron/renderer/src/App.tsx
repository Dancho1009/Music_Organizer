import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ClipboardCheck, Eraser, FileText, FolderTree, History, Play, RotateCcw, ShieldCheck, Trash2, TriangleAlert } from 'lucide-react'
import { PathField } from './components/PathField'
import { BatchToolbar } from './components/BatchToolbar'
import { PlanList } from './components/PlanList'
import { buildBatchLyricsDecision, mergeDecisions } from './hooks/useBatchLyricsActions'
import { useTrackSelection } from './hooks/useTrackSelection'
import type { EngineCommand } from './types/api'
import type { LyricsDeletionPreview, MigrationPlan, PlanHistoryItem, TrackPlan, Verification } from './types/plan'

type Decisions = Record<string, Record<string, string | boolean>>
type CleanupPreview = { count: number; remaining: { counts: Record<string, number> }; empty_directories: string[] }

function resultPlan(value: unknown): MigrationPlan | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as { plan?: MigrationPlan; plan_id?: string; tracks?: unknown[] }
  if (candidate.plan) return candidate.plan
  return candidate.plan_id && Array.isArray(candidate.tracks) ? (candidate as MigrationPlan) : null
}

function resultVerification(value: unknown): Verification | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<Verification>
  return typeof candidate.ok === 'boolean' && Array.isArray(candidate.checks) ? (candidate as Verification) : null
}

export default function App(): JSX.Element {
  const [source, setSource] = useState('')
  const [flacDestination, setFlacDestination] = useState('')
  const [mp3Destination, setMp3Destination] = useState('')
  const [mode, setMode] = useState<'move' | 'link'>('move')
  const [lyricsCleanupOnly, setLyricsCleanupOnly] = useState(false)
  const [plan, setPlan] = useState<MigrationPlan | null>(null)
  const [planPath, setPlanPath] = useState('')
  const [decisions, setDecisions] = useState<Decisions>({})
  const [verification, setVerification] = useState<Verification | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([])
  const [history, setHistory] = useState<PlanHistoryItem[]>([])
  const [visibleRecovery, setVisibleRecovery] = useState('')
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const [trackFilter, setTrackFilter] = useState<'all' | 'blocked' | 'manual_review' | 'warning'>('all')
  const [cleanupPreview, setCleanupPreview] = useState<CleanupPreview | null>(null)
  const [lyricsDeletionPreview, setLyricsDeletionPreview] = useState<LyricsDeletionPreview | null>(null)
  const { selectedTracks, selectedCount, toggleTrack, selectTracks, clearSelection } = useTrackSelection()

  useEffect(() => window.musicOrganizer.onProgress((event) => {
    if (!event || typeof event !== 'object') return
    const progress = event as Record<string, unknown>
    if (progress.event === 'result') return
    setEvents((current) => [...current.slice(-79), progress])
  }), [])

  useEffect(() => {
    void refreshHistory()
  }, [])

  const blocked = useMemo(() => plan?.summary.blocked || 0, [plan])
  const reviewed = useMemo(() => plan?.summary.manual_review || 0, [plan])
  const issueCount = useMemo(() => plan?.tracks.filter((track) => track.issues.length > 0).length || 0, [plan])
  const pendingCount = useMemo(
    () => plan?.tracks.filter((track) => track.status === 'blocked' || track.status === 'manual_review').length || 0,
    [plan]
  )
  const conflictCount = useMemo(
    () => plan?.tracks.filter((track) => track.issues.some((issue) => issue.code === 'different_destination_file' || issue.code === 'source_asset_multiple_destinations')).length || 0,
    [plan]
  )
  const pendingLyricsDeletion = useMemo(
    () => plan?.tracks.filter((track) => track.lyrics.deletion?.requested && track.lyrics.deletion.state !== 'deleted').length || 0,
    [plan]
  )
  const isLyricsCleanupPlan = Boolean(plan?.config.lyrics_cleanup_only)
  const canApply = plan?.status === 'ready' && !isLyricsCleanupPlan
  const canVerify = Boolean(plan && (['applied', 'verify_failed', 'verified'].includes(plan.status) || (isLyricsCleanupPlan && plan.status === 'ready')))
  const interrupted = history.find((item) => item.recovery)
  const visiblePlan = useMemo(() => {
    if (!plan || trackFilter === 'all') return plan
    return { ...plan, tracks: plan.tracks.filter((track) => track.status === trackFilter) }
  }, [plan, trackFilter])

  const selectedPlanTracks = useMemo(
    () => plan?.tracks.filter((track) => selectedTracks.has(track.track_id)) || [],
    [plan, selectedTracks]
  )

  async function choose(setter: (value: string) => void): Promise<void> {
    const selected = await window.musicOrganizer.chooseDirectory()
    if (selected) setter(selected)
  }

  async function run(command: EngineCommand, args: Record<string, string | boolean | undefined>): Promise<unknown | null> {
    setBusy(true)
    setNotice('')
    try {
      const response = await window.musicOrganizer.runEngine(command, args)
      return response.result
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '操作失败。')
      return null
    } finally {
      setBusy(false)
    }
  }

  async function refreshHistory(): Promise<void> {
    try {
      const response = await window.musicOrganizer.runEngine('history', {})
      const value = response.result as { plans?: PlanHistoryItem[] }
      setHistory(Array.isArray(value?.plans) ? value.plans : [])
    } catch {
      setHistory([])
    }
  }

  async function createPlan(): Promise<void> {
    if (!source || (!lyricsCleanupOnly && !flacDestination && !mp3Destination)) {
      setNotice(lyricsCleanupOnly ? '请填写歌词清理源目录。' : '请填写源目录，以及 FLAC 或 MP3 中至少一个目标目录。')
      return
    }
    const value = await run('plan', {
      source,
      ...(!lyricsCleanupOnly && flacDestination ? { 'flac-destination': flacDestination } : {}),
      ...(!lyricsCleanupOnly && mp3Destination ? { 'mp3-destination': mp3Destination } : {}),
      mode,
      decisions: JSON.stringify(decisions),
      ...(!lyricsCleanupOnly && planPath ? { 'parent-plan': planPath } : {}),
      ...(lyricsCleanupOnly ? { 'lyrics-cleanup-only': true } : {})
    })
    const nextPlan = resultPlan(value)
    if (nextPlan) {
      setPlan(nextPlan)
      clearSelection()
      setLyricsCleanupOnly(Boolean(nextPlan.config.lyrics_cleanup_only))
      if (value && typeof value === 'object' && typeof (value as { plan_path?: unknown }).plan_path === 'string') {
        setPlanPath((value as { plan_path: string }).plan_path)
      }
      setVerification(null)
      setReviewConfirmed(false)
      setCleanupPreview(null)
      setEvents([])
      setLyricsDeletionPreview(null)
      setNotice(nextPlan.status === 'ready' ? '计划已生成，可以执行。' : '计划含有待处理项，修正后重新生成。')
      void refreshHistory()
    }
  }

  async function apply(): Promise<void> {
    if (!plan || !window.confirm('执行后会按计划移动或链接文件。是否继续？')) return
    if (!planPath) return
    const value = await run('apply', { plan: planPath })
    const nextPlan = resultPlan(value)
    if (nextPlan) {
      setPlan(nextPlan)
      setNotice('文件操作完成，请执行验证。')
      void refreshHistory()
    }
  }

  async function verify(): Promise<void> {
    if (!plan) return
    if (!planPath) return
    const value = await run('verify', { plan: planPath })
    const result = resultVerification(value)
    if (result) {
      setVerification(result)
      setPlan({ ...plan, status: result.ok ? 'verified' : 'verify_failed' })
      setNotice(result.ok ? (isLyricsCleanupPlan ? '歌词清理计划验证通过。' : '验证通过。') : `验证失败：${result.failed} 项。`)
      void refreshHistory()
    }
  }

  async function rollback(): Promise<void> {
    if (!plan || !window.confirm('回滚会撤销已完成的文件操作。是否继续？')) return
    if (!planPath) return
    const value = await run('rollback', { plan: planPath })
    if (value) {
      setPlan({ ...plan, status: 'rolled_back' })
      setVerification(null)
      setNotice('回滚完成。')
      void refreshHistory()
    }
  }

  async function inspectCleanup(): Promise<void> {
    if (!planPath) return
    const value = await run('cleanup', { plan: planPath, 'include-root': true })
    if (value && typeof value === 'object') setCleanupPreview(value as CleanupPreview)
  }

  async function cleanup(): Promise<void> {
    if (!cleanupPreview || !window.confirm(`将删除 ${cleanupPreview.count} 个空目录。是否继续？`)) return
    if (!planPath) return
    const value = await run('cleanup', { plan: planPath, apply: true, 'include-root': true })
    if (value && typeof value === 'object') {
      const count = (value as { count?: number }).count || 0
      setNotice(`已删除 ${count} 个空目录。`)
      if (plan) setPlan({ ...plan, status: 'cleaned' })
      void refreshHistory()
    }
  }

  async function inspectLyricsDeletion(): Promise<void> {
    if (!planPath || plan?.status !== 'verified') return
    const value = await run('delete-lyrics', { plan: planPath })
    if (value && typeof value === 'object') setLyricsDeletionPreview(value as LyricsDeletionPreview)
  }

  async function deleteLyrics(): Promise<void> {
    if (!lyricsDeletionPreview || lyricsDeletionPreview.count === 0 || !window.confirm(`将永久删除 ${lyricsDeletionPreview.count} 个异常歌词文件，且无法通过迁移回滚恢复。是否继续？`)) return
    if (!planPath) return
    const value = await run('delete-lyrics', { plan: planPath, apply: true })
    if (value && typeof value === 'object') {
      const result = value as LyricsDeletionPreview
      const nextPlan = resultPlan(value)
      if (nextPlan) setPlan(nextPlan)
      setLyricsDeletionPreview(result)
      setNotice(result.ok ? `已删除 ${result.deleted.length} 个异常歌词文件。` : `歌词删除未完全成功，已删除 ${result.deleted.length} 个。`)
      void refreshHistory()
    }
  }

  function ignoreLyrics(track: TrackPlan): void {
    setDecisions((current) => ({ ...current, [track.track_id]: { lyrics_action: 'ignore' } }))
  }

  async function selectLyrics(track: TrackPlan): Promise<void> {
    const selected = await window.musicOrganizer.chooseLrc()
    if (selected) setDecisions((current) => ({ ...current, [track.track_id]: { ...current[track.track_id], lyrics_path: selected } }))
  }

  function confirmLyrics(track: TrackPlan): void {
    setDecisions((current) => ({ ...current, [track.track_id]: { ...current[track.track_id], lyrics_status: 'actual' } }))
  }

  function deleteLyricsDecision(track: TrackPlan): void {
    setDecisions((current) => ({ ...current, [track.track_id]: { ...current[track.track_id], lyrics_action: 'delete' } }))
  }

  function applyBatchLyricsAction(action: 'confirm' | 'ignore' | 'delete'): void {
    if (selectedPlanTracks.length === 0) return
    setDecisions((current) => mergeDecisions(current, buildBatchLyricsDecision(selectedPlanTracks, action)))
    clearSelection()
  }

  function selectAllTracks(): void {
    if (!plan) return
    selectTracks(plan.tracks.map((track) => track.track_id))
  }

  async function openFolder(track: TrackPlan): Promise<void> {
    const opened = await window.musicOrganizer.openPath(track.source_audio)
    if (!opened) setNotice(`无法打开文件夹：${track.source_audio}`)
  }

  async function openLyrics(track: TrackPlan): Promise<void> {
    const lyricsPath = decisions[track.track_id]?.lyrics_path
    const targetPath = typeof lyricsPath === 'string' && lyricsPath ? lyricsPath : track.lyrics.source
    if (!targetPath) {
      setNotice('该歌曲没有可打开的歌词文件。')
      return
    }
    const opened = await window.musicOrganizer.openFile(targetPath)
    if (!opened) setNotice(`无法打开歌词文件：${targetPath}`)
  }

  function excludeTrack(track: TrackPlan): void {
    setDecisions((current) => ({ ...current, [track.track_id]: { exclude: true } }))
  }

  async function resumeInterrupted(item: PlanHistoryItem): Promise<void> {
    const value = await run('resume', { plan: item.plan_path })
    const resumed = resultPlan(value)
    if (resumed) {
      setPlan(resumed)
      setPlanPath(item.plan_path)
      setNotice('中断计划已继续完成，请执行验证。')
    }
    void refreshHistory()
  }

  async function rollbackInterrupted(item: PlanHistoryItem): Promise<void> {
    const value = await run('rollback', { plan: item.plan_path })
    if (value) setNotice('中断计划已回滚。')
    void refreshHistory()
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <div className="eyebrow">MUSIC ORGANIZER</div>
          <h1>音乐整理</h1>
        </div>
        <div className="header-status"><ShieldCheck size={18} />计划、验证、回滚</div>
      </header>

      <section className="configuration" aria-label={lyricsCleanupOnly ? '歌词清理目录' : '迁移目录'}>
        <div className="section-heading"><FolderTree size={19} /><h2>{lyricsCleanupOnly ? '歌词清理' : '迁移目录'}</h2></div>
        <div className="path-grid">
          <PathField label="源目录" value={source} placeholder={String.raw`例如 D:\Music 或 \\server\share\music`} onChange={setSource} onBrowse={() => choose(setSource)} />
          {!lyricsCleanupOnly && <PathField label="FLAC 目标目录（可选）" value={flacDestination} placeholder="按 主艺术家\\完整专辑名 归档" onChange={setFlacDestination} onBrowse={() => choose(setFlacDestination)} />}
          {!lyricsCleanupOnly && <PathField label="MP3 目标目录（可选）" value={mp3Destination} placeholder="按 主艺术家\\完整专辑名 归档" onChange={setMp3Destination} onBrowse={() => choose(setMp3Destination)} />}
        </div>
        <div className="configuration-footer">
          <div className="configuration-options">
            <div className="segmented" aria-label="工作模式">
              <button type="button" className={!lyricsCleanupOnly ? 'selected' : ''} onClick={() => setLyricsCleanupOnly(false)}>迁移整理</button>
              <button type="button" className={lyricsCleanupOnly ? 'selected' : ''} onClick={() => setLyricsCleanupOnly(true)}>仅清理无效歌词</button>
            </div>
            {!lyricsCleanupOnly && <div className="segmented" aria-label="文件操作方式">
              <button type="button" className={mode === 'move' ? 'selected' : ''} onClick={() => setMode('move')}>移动</button>
              <button type="button" className={mode === 'link' ? 'selected' : ''} onClick={() => setMode('link')}>硬链接</button>
            </div>}
          </div>
          <button type="button" className="primary-button" disabled={busy} onClick={createPlan}><ClipboardCheck size={17} />{lyricsCleanupOnly ? '扫描歌词' : '生成迁移计划'}</button>
        </div>
      </section>

      {interrupted?.recovery && <section className="recovery" aria-label="中断恢复">
        <div className="recovery-main">
          <TriangleAlert size={19} />
          <div><strong>检测到未完成迁移</strong><span>{interrupted.plan_id} · {interrupted.recovery.completed_assets} 项已提交</span></div>
        </div>
        <div className="recovery-actions">
          <button type="button" disabled={busy || !interrupted.recovery.can_resume} onClick={() => resumeInterrupted(interrupted)}><Play size={16} />继续</button>
          <button type="button" disabled={busy || !interrupted.recovery.can_rollback} onClick={() => rollbackInterrupted(interrupted)}><RotateCcw size={16} />回滚</button>
          <button type="button" onClick={() => setVisibleRecovery(visibleRecovery === interrupted.plan_id ? '' : interrupted.plan_id)}><FileText size={16} />查看日志</button>
        </div>
        {visibleRecovery === interrupted.plan_id && <div className="recovery-detail"><span>{interrupted.recovery.journal_path}</span><span>可继续：{interrupted.recovery.can_resume ? '是' : '否，磁盘状态与日志不一致'}</span></div>}
      </section>}

      {notice && <div className="notice" role="status"><TriangleAlert size={17} />{notice}</div>}

      {plan ? (
        <>
          <section className="plan-summary" aria-label="计划概览">
            <div className="plan-summary-top">
              <div className="section-heading"><ClipboardCheck size={19} /><h2>计划 {plan.plan_id.slice(-8)}</h2><span>v{plan.plan_version}</span><span className={`state state-${plan.status}`}>{plan.status}</span></div>
              <div className="metrics">
                <div><strong>{plan.summary.tracks || 0}</strong><span>歌曲</span></div>
                <div><strong>{plan.summary.assets || 0}</strong><span>文件</span></div>
                <div className={blocked ? 'metric-alert' : ''}><strong>{blocked}</strong><span>阻断</span></div>
                <div className={reviewed ? 'metric-review' : ''}><strong>{reviewed}</strong><span>待确认</span></div>
              </div>
            </div>
            <div className="plan-controls">
              {!isLyricsCleanupPlan && <label className="review-confirm"><input type="checkbox" checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.target.checked)} />我已检查异常项目</label>}
              <div className="plan-actions">
                {!isLyricsCleanupPlan && <button type="button" disabled={!canApply || !reviewConfirmed || busy} className="primary-button" onClick={apply}><CheckCircle2 size={17} />执行计划</button>}
                <button type="button" disabled={busy || !canVerify} onClick={verify}><ShieldCheck size={17} />{isLyricsCleanupPlan ? '验证清理计划' : '验证'}</button>
                {!isLyricsCleanupPlan && <button type="button" disabled={busy || !['applied', 'failed', 'verify_failed', 'verified'].includes(plan.status)} onClick={rollback}><RotateCcw size={17} />回滚</button>}
                {!isLyricsCleanupPlan && <button type="button" disabled={busy || plan.status !== 'verified'} onClick={inspectCleanup}><Eraser size={17} />检查清理</button>}
                {pendingLyricsDeletion > 0 && <button type="button" disabled={busy || plan.status !== 'verified'} onClick={inspectLyricsDeletion}><Trash2 size={17} />检查异常歌词</button>}
              </div>
            </div>
          </section>

          {verification && <section className={`verification ${verification.ok ? 'verification-ok' : 'verification-failed'}`}>
            {verification.ok ? <CheckCircle2 size={18} /> : <TriangleAlert size={18} />}
            <span>{verification.ok ? `验证通过：${verification.passed} 项文件状态一致。` : `验证失败：${verification.failed} 项不一致。`}</span>
          </section>}

          {cleanupPreview && <section className="cleanup-preview">
            <div><strong>{cleanupPreview.count}</strong><span>可删除空目录</span></div>
            <div><strong>{cleanupPreview.remaining.counts.audio || 0}</strong><span>剩余音频</span></div>
            <div><strong>{cleanupPreview.remaining.counts.lrc || 0}</strong><span>剩余歌词</span></div>
            <div><strong>{cleanupPreview.remaining.counts.cover || 0}</strong><span>剩余封面</span></div>
            <div><strong>{cleanupPreview.remaining.counts.other || 0}</strong><span>其他文件</span></div>
            <button type="button" className="primary-button" disabled={busy || cleanupPreview.count === 0} onClick={cleanup}><Eraser size={17} />确认清理</button>
          </section>}

          {lyricsDeletionPreview && <section className="cleanup-preview lyrics-deletion-preview">
            <div><strong>{lyricsDeletionPreview.count}</strong><span>待永久删除歌词</span></div>
            <div><strong>{lyricsDeletionPreview.blocked.length}</strong><span>阻断项</span></div>
            <button type="button" className="danger-button" disabled={busy || !lyricsDeletionPreview.ok || lyricsDeletionPreview.count === 0} onClick={deleteLyrics}><Trash2 size={17} />确认永久删除</button>
          </section>}

          <section className="review" aria-label="计划明细">
            <div className="section-heading">
              <h2>计划明细</h2>
              <span>{plan.tracks.length} 项</span>
              <div className="review-stats" aria-label="计划明细统计">
                <span className={issueCount ? 'metric-alert' : ''}>异常 {issueCount}</span>
                <span className={pendingCount ? 'metric-review' : ''}>待处理 {pendingCount}</span>
                <span className={conflictCount ? 'metric-alert' : ''}>冲突 {conflictCount}</span>
              </div>
            </div>
            <BatchToolbar
              selectedCount={selectedCount}
              onSelectAll={selectAllTracks}
              onClear={clearSelection}
              onConfirmLyrics={() => applyBatchLyricsAction('confirm')}
              onIgnoreLyrics={() => applyBatchLyricsAction('ignore')}
              onDeleteLyrics={() => applyBatchLyricsAction('delete')}
            />
            <div className="filter-tabs" aria-label="筛选计划明细">
              {(['all', 'blocked', 'manual_review', 'warning'] as const).map((value) => <button type="button" className={trackFilter === value ? 'selected' : ''} key={value} onClick={() => setTrackFilter(value)}>{value === 'all' ? '全部' : value === 'blocked' ? '阻断' : value === 'manual_review' ? '待确认' : '提示'}</button>)}
            </div>
            {visiblePlan && <PlanList
              plan={visiblePlan}
              decisions={decisions}
              selectedTracks={selectedTracks}
              onToggleSelect={(track) => toggleTrack(track.track_id)}
              onOpenFolder={openFolder}
              onOpenLyrics={openLyrics}
              onIgnoreLyrics={ignoreLyrics}
              onSelectLyrics={selectLyrics}
              onConfirmLyrics={confirmLyrics}
              onDeleteLyrics={deleteLyricsDecision}
              onExclude={excludeTrack}
            />}
          </section>
        </>
      ) : (
        <section className="empty-state"><ClipboardCheck size={32} /><span>填写目录后生成计划。</span></section>
      )}

      {events.length > 0 && <section className="activity" aria-label="执行进度"><div className="section-heading"><h2>执行记录</h2><span>{events.length} 条</span></div><div className="event-list">{events.slice(-8).reverse().map((event, index) => <div key={`${String(event.event)}-${index}`}>{String(event.event)}{event.source ? ` · ${String(event.source)}` : ''}</div>)}</div></section>}
      {history.length > 0 && <section className="history" aria-label="计划历史"><div className="section-heading"><History size={19} /><h2>计划历史</h2><span>{history.length} 项</span></div><div className="history-list">{history.slice(0, 8).map((item) => <div key={item.plan_id}><span>{item.plan_id.slice(-10)}</span><span>v{item.plan_version}</span><span className={`state state-${item.status}`}>{item.status}</span><time>{new Date(item.created_at).toLocaleString()}</time></div>)}</div></section>}
    </main>
  )
}
