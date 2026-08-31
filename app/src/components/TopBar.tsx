// 顶栏：导入视频 → 识别 → 翻译 → 导出 主流程 + 设置 + 进度显示
import { useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import TranscribeDialog from './TranscribeDialog'
import TranslateDialog from './TranslateDialog'
import ExportDialog from './ExportDialog'
import SettingsDialog from './SettingsDialog'

export default function TopBar({ sysOk }: { sysOk: { ffmpeg: boolean; cuda: boolean } | null }) {
  const { media, setVideo, tracks, task } = useStore()
  const [dialog, setDialog] = useState<'' | 'transcribe' | 'translate' | 'export' | 'settings'>('')
  const busy = task?.status === 'running'

  async function importVideo() {
    const path = await window.subcraft.openVideoDialog()
    if (!path) return
    try {
      const info = await api.probe(path)
      setVideo(path, info)
    } catch (e) {
      alert(`无法读取视频: ${e instanceof Error ? e.message : e}`)
    }
  }

  return (
    <div className="topbar">
      <div className="topbar-brand">
        <span className="title">🎬 SubCraft 字幕生成器</span>
        <span className="title-badge">LORENTZ MATRIX</span>
      </div>

      <div className="workflow-pipeline">
        <button
          className="quantum-btn btn-import"
          onClick={importVideo}
          disabled={busy}
          title="导入本地视频文件"
        >
          <span className="btn-step">00</span>
          <span>导入视频</span>
        </button>

        <span className="pipeline-connector">›</span>

        <button
          className="quantum-btn primary btn-transcribe"
          disabled={!media || busy}
          onClick={() => setDialog('transcribe')}
          title="识别视频音轨生成字幕"
        >
          <span className="btn-step">01</span>
          <span>识别字幕</span>
        </button>

        <span className="pipeline-connector">›</span>

        <button
          className="quantum-btn primary btn-translate"
          disabled={!tracks.some((t) => t.role === 'source') || busy}
          onClick={() => setDialog('translate')}
          title="将源语言字幕翻译为目标语言"
        >
          <span className="btn-step">02</span>
          <span>翻译</span>
        </button>

        <span className="pipeline-connector">›</span>

        <button
          className="quantum-btn success btn-export"
          disabled={tracks.length === 0 || busy}
          onClick={() => setDialog('export')}
          title="导出 SRT/ASS 文件或封装/烧录视频"
        >
          <span className="btn-step">03</span>
          <span>导出</span>
        </button>
      </div>

      {media && (
        <span className="media-name" title={media.path}>
          [FILE: {media.name}] {media.width}×{media.height} {media.video_codec.toUpperCase()}
        </span>
      )}

      <div className="topbar-right">
        <button
          className="quantum-btn btn-settings"
          onClick={() => setDialog('settings')}
          title="配置 AI 翻译厂商与系统参数"
        >
          ⚙ 设置
        </button>

        {sysOk && (
          <span className="sys-diag">
            <span>
              <span className={`status-dot ${sysOk.ffmpeg ? 'ok' : 'bad'}`} />
              FFMPEG
            </span>
            <span style={{ marginLeft: 6 }}>
              <span className={`status-dot ${sysOk.cuda ? 'ok' : 'bad'}`} />
              {sysOk.cuda ? 'CUDA' : 'CPU'}
            </span>
          </span>
        )}

        <div className="progress-wrap">
          {task && (
            <>
              <div className="progress-bar">
                <div style={{ width: `${(task.progress * 100).toFixed(0)}%` }} />
              </div>
              <span className="progress-msg" title={task.message}>
                [{task.label}] {task.status === 'error' ? `FAIL: ${task.error}` : task.message}
              </span>
            </>
          )}
        </div>
      </div>

      {dialog === 'transcribe' && <TranscribeDialog onClose={() => setDialog('')} />}
      {dialog === 'translate' && <TranslateDialog onClose={() => setDialog('')} />}
      {dialog === 'export' && <ExportDialog onClose={() => setDialog('')} />}
      {dialog === 'settings' && <SettingsDialog onClose={() => setDialog('')} />}
    </div>
  )
}
