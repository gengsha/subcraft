// 导出对话框：字幕文件 (SRT/ASS) + 视频（软字幕封装 MKV 无损 / 硬字幕内嵌烧录进画面）
// 内嵌模式带"真实烧录预览帧"：用与最终导出相同的 ffmpeg+libass 管线渲染，所见即所得
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, waitTask } from '../api'
import { useStore } from '../store'

/** 读取播放器当前播放时间（用于预览帧默认时间点） */
function playerTime(): number {
  return document.querySelector<HTMLVideoElement>('.video-area video')?.currentTime ?? 0
}

export default function ExportDialog({ onClose }: { onClose: () => void }) {
  const { tracks, bilingual, primaryTrackId, media, videoPath, setTask } = useStore()
  const baseName = (media?.name ?? 'subtitle').replace(/\.[^.]+$/, '')
  const [doSrt, setDoSrt] = useState(true)
  const [doAss, setDoAss] = useState(true)
  const [doVideo, setDoVideo] = useState(true)
  const [hard, setHard] = useState(false)            // 视频导出方式：false=软字幕封装 / true=内嵌烧录
  const [burnTrackId, setBurnTrackId] = useState('') // '' = 自动（双语优先）
  const [previewTime, setPreviewTime] = useState(() => playerTime().toFixed(2))
  const [preview, setPreview] = useState<{ img: string; loading: boolean; err: string }>({ img: '', loading: false, err: '' })
  const [msg, setMsg] = useState('')

  // 烧录预览帧：样式/轨道/时间变化后防抖刷新
  useEffect(() => {
    if (!doVideo || !hard || !media) return
    let cancelled = false
    setPreview((p) => ({ ...p, loading: true }))
    const timer = setTimeout(async () => {
      try {
        const r = await api.previewFrame({
          tracks, bilingual, primary_id: primaryTrackId,
          width: media.width || 1920, height: media.height || 1080,
          video_path: videoPath, burn_track_id: burnTrackId || null,
          time: parseFloat(previewTime) || 0,
        })
        if (!cancelled) setPreview({ img: r.image, loading: false, err: '' })
      } catch (e) {
        if (!cancelled) setPreview((p) => ({ ...p, loading: false, err: e instanceof Error ? e.message : String(e) }))
      }
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [doVideo, hard, media, tracks, bilingual, primaryTrackId, videoPath, burnTrackId, previewTime])

  async function run() {
    if (!media) return
    setMsg('')
    try {
      const common = {
        tracks, bilingual, primary_id: primaryTrackId,
        width: media.width || 1920, height: media.height || 1080,
      }
      if (doSrt || doAss) {
        const dir = await window.subcraft.selectDirDialog()
        if (dir) {
          const formats = [doSrt && 'srt', doAss && 'ass'].filter(Boolean) as string[]
          const r = await api.exportSubtitles({ ...common, out_dir: dir, base_name: baseName, formats })
          setMsg(`已导出 ${r.files.length} 个字幕文件`)
        }
      }
      if (doVideo) {
        const ext = hard ? 'mp4' : 'mkv'
        const out = await window.subcraft.saveFileDialog(`${baseName}_${hard ? '内嵌' : 'sub'}.${ext}`, ext)
        if (out) {
          const { task_id } = await api.exportVideo({
            ...common, video_path: videoPath, out_path: out,
            mode: hard ? 'hard' : 'soft',
            burn_track_id: hard && burnTrackId ? burnTrackId : null,
          })
          setTask({ task_id, status: 'running', progress: 0, message: hard ? '内嵌字幕中' : '封装中', error: null, label: '导出' })
          await waitTask(task_id, (t) => setTask({ ...t, label: '导出' }))
          setTask(null)
          setMsg((m) => `${m}${m ? '；' : ''}${hard ? '视频已导出（字幕已烧录进画面）' : '视频已导出（软字幕封装）'}`)
        }
      }
      if (!doSrt && !doAss && !doVideo) setMsg('请至少选择一项')
    } catch (e) {
      setMsg(`导出失败: ${e instanceof Error ? e.message : e}`)
    }
  }

  return createPortal(
    <div className="dialog-mask" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>③ 导出</h3>
        <div className="row"><label>导出内容</label>
          <div className="checkbox-row">
            <label><input type="checkbox" checked={doSrt} onChange={(e) => setDoSrt(e.target.checked)} />SRT 字幕文件</label>
            <label><input type="checkbox" checked={doAss} onChange={(e) => setDoAss(e.target.checked)} />ASS 字幕文件（含字体样式）</label>
            <label><input type="checkbox" checked={doVideo} onChange={(e) => setDoVideo(e.target.checked)} />导出视频</label>
          </div>
        </div>
        {doVideo && (
          <div className="row"><label>视频方式</label>
            <div className="checkbox-row">
              <label><input type="radio" name="vmode" checked={!hard} onChange={() => setHard(false)} />软字幕封装</label>
              <label><input type="radio" name="vmode" checked={hard} onChange={() => setHard(true)} />内嵌字幕（烧录进画面）</label>
            </div>
          </div>
        )}
        {doVideo && hard && (
          <div className="row"><label>烧录内容</label>
            <select value={burnTrackId} onChange={(e) => setBurnTrackId(e.target.value)}>
              <option value="">自动{bilingual && tracks.length >= 2 ? '（双语）' : '（主字幕轨）'}</option>
              {tracks.map((t) => (
                <option key={t.id} value={t.id}>{t.label || t.language}</option>
              ))}
            </select>
          </div>
        )}
        {doVideo && hard && (
          <div className="burn-preview">
            <div className="row" style={{ marginBottom: 6 }}>
              <label>预览时间(秒)</label>
              <input
                value={previewTime}
                onChange={(e) => setPreviewTime(e.target.value)}
                style={{ flex: '0 0 90px' }}
              />
              <button onClick={() => setPreviewTime(playerTime().toFixed(2))}>取播放器当前画面</button>
            </div>
            {preview.err ? (
              <div className="hint" style={{ color: 'var(--danger)' }}>预览失败: {preview.err}</div>
            ) : preview.img ? (
              <img className={preview.loading ? 'loading' : ''} src={preview.img} alt="烧录效果预览" />
            ) : (
              <div className="hint">正在生成预览帧...</div>
            )}
            <div className="hint">预览与最终内嵌使用同一渲染引擎（ffmpeg + libass），所见即所得</div>
          </div>
        )}
        <div className="hint">
          · 每种语言导出单独文件{bilingual && tracks.length >= 2 ? '，另附双语合并文件' : ''}<br />
          · 软字幕封装：MKV 内嵌可开关字幕轨，视频流直接复制，<b>画质 100% 无损</b>，秒级完成（另附 SRT 兼容轨）。注意：Windows
          自带播放器不支持 ASS 软字幕，请用 <b>VLC / PotPlayer / mpv</b> 查看<br />
          · 内嵌字幕：字幕直接烧录进画面，<b>任何播放器都能看到</b>，需重新编码视频，速度较慢（crf 18 高质量）
        </div>
        {msg && <div className="hint" style={{ color: msg.startsWith('导出失败') ? 'var(--danger)' : 'var(--accent2)' }}>{msg}</div>}
        <div className="actions">
          <button onClick={onClose}>关闭</button>
          <button className="success" onClick={run}>开始导出</button>
        </div>
      </div>
    </div>,
    document.body
  )
}
