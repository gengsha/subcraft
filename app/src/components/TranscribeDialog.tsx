// 识别字幕对话框：选择引擎(本地GPU/云端API)、模型、语言
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, waitTask } from '../api'
import { newTrack, useStore } from '../store'
import { LANGUAGES, type Segment } from '../types'

export default function TranscribeDialog({ onClose }: { onClose: () => void }) {
  const { media, videoPath, upsertTrack, setTask } = useStore()
  const [engine, setEngine] = useState<'local' | 'openai'>('local')
  const [model, setModel] = useState('large-v3-turbo')
  const [language, setLanguage] = useState('auto')
  const [models, setModels] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')

  useEffect(() => {
    api.whisperModels().then(setModels).catch(() => {})
    api.getConfig().then((c) => { if (c.whisper_model) setModel(c.whisper_model) }).catch(() => {})
  }, [])

  async function start() {
    if (!media) return
    onClose()
    try {
      const { task_id } = await api.transcribe({
        video_path: videoPath, duration: media.duration,
        engine, model: engine === 'local' ? model : null,
        language: language === 'auto' ? null : language,
      })
      setTask({ task_id, status: 'running', progress: 0, message: '启动中', error: null, label: '识别' })
      const result = await waitTask(task_id, (t) => setTask({ ...t, label: '识别' }))
      const segments = (result.segments ?? []) as Segment[]
      const lang = (result.language as string) || 'und'
      if (segments.length === 0) {
        setTask({ task_id, status: 'error', progress: 1, message: '', error: '未识别到语音内容', label: '识别' })
        return
      }
      upsertTrack(newTrack({ language: lang, role: 'source', segments, label: LANGUAGES[lang] ?? lang }))
      setTask(null)
    } catch (e) {
      setTask({ task_id: '', status: 'error', progress: 1, message: '', error: e instanceof Error ? e.message : String(e), label: '识别' })
    }
  }

  return createPortal(
    <div className="dialog-mask" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>① 识别字幕（语音转写）</h3>
        <div className="row">
          <label>识别引擎</label>
          <select value={engine} onChange={(e) => setEngine(e.target.value as 'local' | 'openai')}>
            <option value="local">本地 faster-whisper（GPU 加速，免费）</option>
            <option value="openai">OpenAI Whisper API（云端，需 API Key）</option>
          </select>
        </div>
        {engine === 'local' ? (
          <div className="row">
            <label>模型</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {Object.entries(models).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              {Object.keys(models).length === 0 && <option value={model}>{model}</option>}
            </select>
          </div>
        ) : (
          <div className="hint">将使用「设置」中的 OpenAI 兼容接口配置（whisper-1 模型）。<br />注意：云端接口按用量计费，且单文件上限 25MB。</div>
        )}
        <div className="row">
          <label>视频语言</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {Object.entries(LANGUAGES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        {err && <div className="hint" style={{ color: 'var(--danger)' }}>{err}</div>}
        <div className="actions">
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={() => { setErr(''); start() }}>开始识别</button>
        </div>
      </div>
    </div>,
    document.body
  )
}
