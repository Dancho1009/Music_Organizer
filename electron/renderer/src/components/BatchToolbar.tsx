import { Check, ListRestart, Trash2, X } from 'lucide-react'

interface BatchToolbarProps {
  selectedCount: number
  onSelectAll(): void
  onClear(): void
  onConfirmLyrics(): void
  onIgnoreLyrics(): void
  onDeleteLyrics(): void
}

export function BatchToolbar({
  selectedCount,
  onSelectAll,
  onClear,
  onConfirmLyrics,
  onIgnoreLyrics,
  onDeleteLyrics
}: BatchToolbarProps): JSX.Element {
  return (
    <section className="batch-toolbar" aria-label="批量操作">
      <div className="batch-summary">已选择 {selectedCount} 项</div>
      <div className="batch-actions">
        <button type="button" onClick={onSelectAll}>全选</button>
        <button type="button" onClick={onClear}><X size={15} />取消选择</button>
        <button type="button" disabled={selectedCount === 0} onClick={onConfirmLyrics}><Check size={15} />批量确认歌词</button>
        <button type="button" disabled={selectedCount === 0} onClick={onIgnoreLyrics}><ListRestart size={15} />批量忽略歌词</button>
        <button type="button" disabled={selectedCount === 0} onClick={onDeleteLyrics}><Trash2 size={15} />批量删除歌词</button>
      </div>
    </section>
  )
}
