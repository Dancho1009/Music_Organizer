import { FolderOpen } from 'lucide-react'

interface PathFieldProps {
  label: string
  value: string
  placeholder: string
  onChange(value: string): void
  onBrowse(): void
}

export function PathField({ label, value, placeholder, onChange, onBrowse }: PathFieldProps): JSX.Element {
  return (
    <label className="path-field">
      <span>{label}</span>
      <div className="path-control">
        <input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
        <button className="icon-button" type="button" onClick={onBrowse} title={`选择${label}`} aria-label={`选择${label}`}>
          <FolderOpen size={18} />
        </button>
      </div>
    </label>
  )
}
