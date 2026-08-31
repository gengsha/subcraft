// 全局状态 (zustand)
import { create } from 'zustand'
import type { MediaInfo, SubtitleTrack, TaskState } from './types'
import { DEFAULT_STYLE } from './types'

let uid = 0
export const nextId = () => `t${Date.now().toString(36)}_${uid++}`

interface ProjectState {
  videoPath: string
  media: MediaInfo | null
  tracks: SubtitleTrack[]
  activeTrackId: string | null
  bilingual: boolean
  primaryTrackId: string | null
  task: (TaskState & { label?: string }) | null
  fonts: Record<string, string>
  seekTo: number | null  // 请求播放器跳转(秒)，消费后清零

  setVideo: (path: string, media: MediaInfo) => void
  setTracks: (tracks: SubtitleTrack[]) => void
  upsertTrack: (track: SubtitleTrack) => void
  removeTrack: (id: string) => void
  updateTrack: (id: string, patch: Partial<SubtitleTrack>) => void
  updateSegment: (trackId: string, index: number, text: string, start?: number, end?: number) => void
  removeSegment: (trackId: string, index: number) => void
  removeEmptySegments: () => void
  setActiveTrack: (id: string) => void
  setBilingual: (v: boolean) => void
  setPrimaryTrack: (id: string) => void
  setTask: (t: (TaskState & { label?: string }) | null) => void
  setFonts: (f: Record<string, string>) => void
  requestSeek: (t: number) => void
  clearSeek: () => void
}

export const useStore = create<ProjectState>((set) => ({
  videoPath: '',
  media: null,
  tracks: [],
  activeTrackId: null,
  bilingual: true,
  primaryTrackId: null,
  task: null,
  fonts: {},
  seekTo: null,

  setVideo: (videoPath, media) => set({ videoPath, media, tracks: [], activeTrackId: null, primaryTrackId: null }),
  setTracks: (tracks) => set({ tracks }),
  upsertTrack: (track) =>
    set((s) => {
      const i = s.tracks.findIndex((t) => t.id === track.id)
      const tracks = i >= 0 ? s.tracks.map((t) => (t.id === track.id ? track : t)) : [...s.tracks, track]
      return {
        tracks,
        activeTrackId: s.activeTrackId ?? track.id,
        primaryTrackId: s.primaryTrackId ?? (track.role === 'source' ? track.id : null),
      }
    }),
  removeTrack: (id) =>
    set((s) => ({
      tracks: s.tracks.filter((t) => t.id !== id),
      activeTrackId: s.activeTrackId === id ? (s.tracks.find((t) => t.id !== id)?.id ?? null) : s.activeTrackId,
      primaryTrackId: s.primaryTrackId === id ? null : s.primaryTrackId,
    })),
  updateTrack: (id, patch) =>
    set((s) => ({ tracks: s.tracks.map((t) => (t.id === id ? { ...t, ...patch } : t)) })),
  updateSegment: (trackId, index, text, start, end) =>
    set((s) => ({
      tracks: s.tracks.map((t) =>
        t.id === trackId
          ? { ...t, segments: t.segments.map((seg, i) => (i === index ? { ...seg, text, start: start ?? seg.start, end: end ?? seg.end } : seg)) }
          : t,
      ),
    })),
  removeSegment: (trackId, index) =>
    set((s) => ({
      tracks: s.tracks.map((t) =>
        t.id === trackId ? { ...t, segments: t.segments.filter((_, i) => i !== index) } : t,
      ),
    })),
  removeEmptySegments: () =>
    set((s) => ({
      tracks: s.tracks.map((t) => ({ ...t, segments: t.segments.filter((seg) => seg.text.trim() !== '') })),
    })),
  setActiveTrack: (activeTrackId) => set({ activeTrackId }),
  setBilingual: (bilingual) => set({ bilingual }),
  setPrimaryTrack: (primaryTrackId) => set({ primaryTrackId }),
  setTask: (task) => set({ task }),
  setFonts: (fonts) => set({ fonts }),
  requestSeek: (seekTo) => set({ seekTo }),
  clearSeek: () => set({ seekTo: null }),
}))

export function newTrack(partial: Partial<SubtitleTrack>): SubtitleTrack {
  return {
    id: nextId(),
    language: 'und',
    label: '',
    role: 'source',
    segments: [],
    style: { ...DEFAULT_STYLE },
    ...partial,
  }
}
