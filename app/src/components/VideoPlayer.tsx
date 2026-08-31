// 视频播放器：jassub (libass WebAssembly) 实时渲染 ASS 字幕预览
import { useEffect, useRef } from 'react'
import JASSUB from 'jassub'
// @ts-ignore vite ?url 导入
import workerUrl from 'jassub/dist/jassub-worker.js?url'
// @ts-ignore
import wasmUrl from 'jassub/dist/jassub-worker.wasm?url'
// @ts-ignore
import legacyWasmUrl from 'jassub/dist/jassub-worker-modern.wasm?url'
// @ts-ignore
import fallbackFont from 'jassub/dist/default.woff2?url'
import { api } from '../api'
import { useStore } from '../store'
import ProgressOverlay from './ProgressOverlay'
import LorenzCanvas from './LorenzCanvas'

export default function VideoPlayer() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const jassubRef = useRef<JASSUB | null>(null)
  const fontsKeyRef = useRef('')
  const fontCacheRef = useRef<Map<string, Uint8Array>>(new Map())
  const lastAssRef = useRef('')               // 最近一次生成的完整 ASS（拖动时本地改写用）
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const { videoPath, media, tracks, bilingual, primaryTrackId, seekTo, clearSeek } = useStore()

  // 跳转请求（点击字幕行）
  useEffect(() => {
    if (seekTo != null && videoRef.current) {
      videoRef.current.currentTime = seekTo
      clearSeek()
    }
  }, [seekTo])

  // 视频元素尺寸变化（窗口缩放/最大化）→ 重算 jassub 画布位置与大小
  useEffect(() => {
    const video = videoRef.current
    if (!video || !videoPath) return
    const ro = new ResizeObserver(() => jassubRef.current?.resize())
    ro.observe(video)
    return () => ro.disconnect()
  }, [videoPath])

  // 字幕/样式变化 → 防抖重新生成 ASS → 刷新预览
  useEffect(() => {
    if (!videoPath || tracks.length === 0) {
      if (jassubRef.current) { jassubRef.current.destroy(); jassubRef.current = null; fontsKeyRef.current = '' }
      return
    }
    clearTimeout(debounceRef.current)
    // 拖动定位期间用短防抖让字幕跟手，其余操作 150ms 合并
    debounceRef.current = setTimeout(async () => {
      try {
        const { ass } = await api.previewAss({
          tracks, bilingual, primary_id: primaryTrackId,
          width: media?.width || 1920, height: media?.height || 1080,
        })
        await renderAss(ass)
      } catch (e) { console.warn('字幕预览刷新失败:', e) }
    }, dragActiveRef.current ? 30 : 150)
    return () => clearTimeout(debounceRef.current)
  }, [videoPath, tracks, bilingual, primaryTrackId, media])

  // ---- 拖动字幕定位（中心点模式）：按住画面拖动 → 字幕中心点坐标实时跟随鼠标 ----
  const dragActiveRef = useRef(false)
  const dragRef = useRef<{
    rect: DOMRect; contentW: number; contentH: number; offX: number; offY: number
    videoW: number; videoH: number
  } | null>(null)
  const dragPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 })
  const dragRafRef = useRef(0)
  const lastStoreSyncRef = useRef(0)

  /** ASS 内当前拖动轨对应的样式名：双语 0=Main(主轨) 1=Sub(副轨)；单语按生成规则 SubCraft_语言_角色 */
  function activeStyleName(): string {
    const { tracks, bilingual, primaryTrackId, activeTrackId } = useStore.getState()
    const track = tracks.find((t) => t.id === activeTrackId)
    if (!track) return ''
    if (bilingual && tracks.length >= 2) return track.id === primaryTrackId ? 'Main' : 'Sub'
    return `SubCraft_${track.language}_${track.role}`
  }

  /** 只改写指定样式 Dialogue 行的位置为 (x,y)；原本没有 \pos 时注入到该行文本字段行首 */
  function rewriteAssPos(ass: string, x: number, y: number, styleName: string): string {
    if (!styleName) return ass
    const esc = styleName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // Dialogue 行格式：Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
    const re = new RegExp(`^(Dialogue:(?:[^,\\n]*,){3}${esc},(?:[^,\\n]*,){5})`, 'gm')
    return ass.replace(re, (prefix) => {
      if (/\\pos\(/.test(prefix)) {
        return prefix.replace(/\\pos\(-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?\)/g, `\\pos(${x},${y})`)
      }
      return prefix + `{\\an5\\pos(${x},${y})}`
    })
  }

  function startDrag(e: React.PointerEvent<HTMLDivElement>) {
    const video = videoRef.current
    if (e.button !== 0 || !video || useStore.getState().tracks.length === 0) return
    if (document.querySelector('.progress-overlay')) return   // 任务进度覆盖层显示期间不拖动
    const rect = video.getBoundingClientRect()
    if (e.clientY > rect.bottom - 56) return                  // 底部播放器控制条区域不作为拖动起点
    const st = useStore.getState()
    const vw = st.media?.width || video.videoWidth || 16
    const vh = st.media?.height || video.videoHeight || 9
    const aspect = vw / vh
    let contentW = rect.width, contentH = rect.height
    if (contentW / contentH > aspect) contentW = contentH * aspect
    else contentH = contentW / aspect
    const offX = (rect.width - contentW) / 2
    const offY = (rect.height - contentH) / 2
    const x = Math.round(Math.min(Math.max(e.clientX - rect.left - offX, 0), contentW) * vw / contentW)
    const y = Math.round(Math.min(Math.max(e.clientY - rect.top - offY, 0), contentH) * vh / contentH)
    dragActiveRef.current = true
    dragRef.current = { rect, contentW, contentH, offX, offY, videoW: vw, videoH: vh }
    dragPosRef.current = { x, y }
    // 首次拖动：以按下点为中心进入坐标模式（触发一次正式预览生成带 \pos 的 ASS）
    const track = st.tracks.find((t) => t.id === st.activeTrackId)
    if (track && (track.style.pos_x == null || track.style.pos_y == null)) {
      st.updateTrack(track.id, { style: { ...track.style, pos_x: x, pos_y: y } })
      lastStoreSyncRef.current = performance.now()
    }
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 非真实指针（如测试合成事件）忽略 */ }
  }

  function moveDrag(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return
    cancelAnimationFrame(dragRafRef.current)
    dragRafRef.current = requestAnimationFrame(() => applyDrag(e.clientX, e.clientY))
  }

  function applyDrag(clientX: number, clientY: number, final = false) {
    const d = dragRef.current
    if (!d) return
    const dx = Math.min(Math.max(clientX - d.rect.left - d.offX, 0), d.contentW)
    const dy = Math.min(Math.max(clientY - d.rect.top - d.offY, 0), d.contentH)
    const x = Math.round(dx * d.videoW / d.contentW)
    const y = Math.round(dy * d.videoH / d.contentH)
    dragPosRef.current = { x, y }
    const inst = jassubRef.current
    if (lastAssRef.current && inst) {
      inst.setTrack(rewriteAssPos(lastAssRef.current, x, y, activeStyleName()))
      if (videoRef.current?.paused) inst.resize()
    }
    if (final || performance.now() - lastStoreSyncRef.current > 150) {
      lastStoreSyncRef.current = performance.now()
      const st = useStore.getState()
      const track = st.tracks.find((t) => t.id === st.activeTrackId)
      if (track && (track.style.pos_x !== x || track.style.pos_y !== y)) {
        st.updateTrack(track.id, { style: { ...track.style, pos_x: x, pos_y: y } })
      }
    }
  }

  function endDrag(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return
    cancelAnimationFrame(dragRafRef.current)
    applyDrag(e.clientX, e.clientY, true)
    dragRef.current = null
    dragActiveRef.current = false
  }

  async function renderAss(ass: string) {
    const video = videoRef.current
    if (!video) return
    lastAssRef.current = ass
    if (dragActiveRef.current) return
    const families = [...new Set(useStore.getState().tracks.map((t) => t.style.font_name))]
    const fontsKey = families.join('|')
    if (jassubRef.current && fontsKeyRef.current === fontsKey) {
      jassubRef.current.setTrack(ass)
      if (video.paused) jassubRef.current.resize()
      return
    }
    jassubRef.current?.destroy()
    const fontBuffers: Uint8Array[] = []
    for (const fam of families) {
      try {
        const cached = fontCacheRef.current.get(fam)
        if (cached) { fontBuffers.push(cached); continue }
        const res = await fetch(api.fontFileUrl(fam))
        if (res.ok) {
          const buf = new Uint8Array(await res.arrayBuffer())
          fontCacheRef.current.set(fam, buf)
          fontBuffers.push(buf)
        }
      } catch { /* 字体缺失则用回退字体 */ }
    }
    const inst = new JASSUB({
      video,
      subContent: ass,
      workerUrl,
      wasmUrl,
      legacyWasmUrl,
      availableFonts: { 'liberation sans': fallbackFont },
      fallbackFont: 'liberation sans',
      fonts: fontBuffers,
    } as unknown as ConstructorParameters<typeof JASSUB>[0])
    jassubRef.current = inst
    fontsKeyRef.current = fontsKey
    ;(window as unknown as Record<string, unknown>).__subcraft_jassub = inst
    if (video.paused) inst.resize()
  }

  return (
    <div
      className="video-area"
      onPointerDown={startDrag}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <div className="hud-corner tl" />
      <div className="hud-corner tr" />
      <div className="hud-corner bl" />
      <div className="hud-corner br" />

      {videoPath ? (
        <video ref={videoRef} src={api.streamUrl(videoPath)} controls crossOrigin="anonymous" />
      ) : (
        <div className="video-empty">
          <LorenzCanvas className="lorenz-bg" opacity={0.65} interactive scaleMultiplier={1.2} />
          <div className="empty-card">
            <div className="big big-icon">🎬</div>
            <div className="empty-title">点击左上角「导入视频」开始</div>
            <div className="empty-sub">[TOPOLOGY: LORENTZ-3D // READY]</div>
          </div>
        </div>
      )}
      <ProgressOverlay />
    </div>
  )
}

/** 秒 -> HH:MM:SS.mmm */
export function fmtTime(sec: number): string {
  const ms = Math.round(sec * 1000)
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const mmm = ms % 1000
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(mmm).padStart(3, '0')}`
}

export function parseTime(text: string): number | null {
  const m = text.trim().match(/^(?:(\d+):)?([0-5]?\d):([0-5]?\d)[.,](\d{1,3})$/)
  if (!m) return null
  const h = m[1] ? parseInt(m[1]) : 0
  return h * 3600 + parseInt(m[2]) * 60 + parseInt(m[3]) + parseInt(m[4].padEnd(3, '0')) / 1000
}
