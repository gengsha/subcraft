// 后端 API 客户端 + WebSocket 任务进度
import type { AppConfig, MediaInfo, Segment, SubtitleTrack, TaskState, TimelineInfo, TimingIssue } from './types'

const base = () => window.subcraft.apiBase
const token = () => window.subcraft.token || ''
/** 给无法自定义请求头的 URL（<video src>、WebSocket）附加令牌 */
const withToken = (url: string) => {
  const t = token()
  return t ? `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(t)}` : url
}

async function req<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(base() + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-SubCraft-Token': token() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const j = await res.json()
      msg = j.detail || msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  probe: (path: string) => req<MediaInfo>('/api/media/probe', { path }),
  fonts: () => req<Record<string, string>>('/api/media/fonts'),
  streamUrl: (path: string) => withToken(`${base()}/api/media/stream?path=${encodeURIComponent(path)}`),
  fontFileUrl: (family: string) => withToken(`${base()}/api/media/fonts/file?family=${encodeURIComponent(family)}`),

  transcribe: (p: {
    video_path: string; duration: number; engine: string; model?: string | null
    language?: string | null; api_key?: string | null; base_url?: string | null
  }) => req<{ task_id: string }>('/api/transcribe', p),

  translate: (p: {
    segments: Segment[]; source_lang: string; target_lang: string
    provider: string; provider_id?: string | null
    api_key?: string | null; base_url?: string | null; model?: string | null
  }) => req<{ task_id: string }>('/api/translate', p),

  testTranslate: (p: { provider: string; provider_id?: string | null }) =>
    req<{ ok: boolean; message: string; latency_ms: number }>('/api/translate/test', p),

  task: (id: string) => req<TaskState & { result: unknown }>(`/api/tasks/${id}`),

  previewAss: (p: {
    tracks: SubtitleTrack[]; bilingual: boolean; primary_id: string | null
    width: number; height: number
  }) => req<{ ass: string }>('/api/export/preview_ass', p),

  exportSubtitles: (p: {
    tracks: SubtitleTrack[]; bilingual: boolean; primary_id: string | null
    width: number; height: number; out_dir: string; base_name: string; formats: string[]
  }) => req<{ files: string[] }>('/api/export/subtitles', p),

  exportVideo: (p: {
    tracks: SubtitleTrack[]; bilingual: boolean; primary_id: string | null
    width: number; height: number; video_path: string; out_path: string
    mode?: 'soft' | 'hard'
    burn_track_id?: string | null
  }) => req<{ task_id: string }>('/api/export/video', p),

  previewFrame: (p: {
    tracks: SubtitleTrack[]; bilingual: boolean; primary_id: string | null
    width: number; height: number; video_path: string
    burn_track_id?: string | null; time: number
  }) => req<{ image: string }>('/api/export/preview_frame', p),

  timelineCheck: (p: { segments: Segment[]; max_cps?: number; max_duration?: number }) =>
    req<{ issues: TimingIssue[] }>('/api/timeline/check', p),

  timelineCuts: (p: { video_path: string; threshold?: number }) =>
    req<{ task_id: string }>('/api/timeline/cuts', p),

  timelineApply: (p: {
    tracks: SubtitleTrack[]; track_id: string
    op: 'split' | 'merge' | 'shift' | 'snap' | 'fix_overlaps'
    sync?: boolean; index?: number; at_time?: number | null; text?: string | null
    first?: number; last?: number; offset?: number; scale?: number; from_time?: number | null
    cuts?: number[]; tolerance?: number
  }) => req<{ tracks: SubtitleTrack[]; info: TimelineInfo; issues: TimingIssue[] }>('/api/timeline/apply', p),

  getConfig: () => req<AppConfig>('/api/config'),
  saveConfig: (cfg: Partial<AppConfig>) => req<AppConfig>('/api/config', cfg),
  systemStatus: () => req<{ ffmpeg: string | null; ffmpeg_ready: boolean; cuda_available: boolean }>('/api/config/system'),
  whisperModels: () => req<Record<string, string>>('/api/whisper_models'),
}

/** 等待任务完成（轮询兜底，WebSocket 推送为主） */
export function waitTask(
  taskId: string,
  onProgress: (t: TaskState) => void,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let settled = false
    const poll = async () => {
      try {
        const t = await api.task(taskId)
        onProgress(t)
        if (t.status === 'done' && !settled) { settled = true; resolve((t.result ?? {}) as Record<string, unknown>) }
        else if (t.status === 'error' && !settled) { settled = true; reject(new Error(t.error || '任务失败')) }
        else if (!settled) setTimeout(poll, 500)
      } catch (e) { if (!settled) { settled = true; reject(e) } }
    }
    poll()
  })
}

/** 连接 WebSocket（进度推送），返回关闭函数 */
export function connectWs(onTask: (t: TaskState & { task_id: string }) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 0
  const connect = () => {
    if (closed) return
    ws = new WebSocket(withToken(`${window.subcraft.wsBase}/ws`))
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data.type === 'task') onTask(data)
      } catch { /* ignore */ }
    }
    ws.onclose = () => { if (!closed && retry++ < 20) setTimeout(connect, 1000) }
    ws.onerror = () => ws?.close()
  }
  connect()
  return () => { closed = true; ws?.close() }
}
