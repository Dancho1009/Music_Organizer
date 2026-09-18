import { useMemo, useState } from 'react'

export function useTrackSelection() {
  const [selectedTracks, setSelectedTracks] = useState<Set<string>>(new Set())

  const selectedCount = selectedTracks.size

  const toggleTrack = (trackId: string): void => {
    setSelectedTracks((current) => {
      const next = new Set(current)
      if (next.has(trackId)) {
        next.delete(trackId)
      } else {
        next.add(trackId)
      }
      return next
    })
  }

  const selectTracks = (trackIds: string[]): void => {
    setSelectedTracks(new Set(trackIds))
  }

  const clearSelection = (): void => {
    setSelectedTracks(new Set())
  }

  return useMemo(() => ({
    selectedTracks,
    selectedCount,
    toggleTrack,
    selectTracks,
    clearSelection
  }), [selectedTracks, selectedCount])
}
