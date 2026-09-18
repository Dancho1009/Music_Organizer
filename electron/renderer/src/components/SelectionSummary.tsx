import { CheckSquare } from 'lucide-react'

interface SelectionSummaryProps {
  count: number
}

export function SelectionSummary({ count }: SelectionSummaryProps): JSX.Element {
  return (
    <div className="selection-summary" aria-live="polite">
      <CheckSquare size={16} />
      <span>已选择 {count} 项，可执行批量操作</span>
    </div>
  )
}
