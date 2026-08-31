// 设置对话框：AI 翻译厂商（OpenAI 兼容，可多家）与 DeepL 分区管理，支持测试连接
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import type { AiProvider, AppConfig } from '../types'
import { AI_PRESETS } from '../types'

type TestResult = { ok: boolean; message: string } | 'testing'

export default function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [saved, setSaved] = useState(false)
  const [tests, setTests] = useState<Record<string, TestResult>>({})

  useEffect(() => { api.getConfig().then(setCfg).catch(() => {}) }, [])

  if (!cfg) return null
  const providers = cfg.ai_providers ?? []

  const set = (k: string, v: unknown) => { setCfg({ ...cfg, [k]: v }); setSaved(false) }
  const setProvider = (id: string, patch: Partial<AiProvider>) => {
    set('ai_providers', providers.map((p) => (p.id === id ? { ...p, ...patch } : p)))
    setTests((t) => ({ ...t, [id]: undefined as unknown as TestResult }))
  }
  const addProvider = (preset?: (typeof AI_PRESETS)[number]) => {
    const id = `p${Date.now().toString(36)}`
    set('ai_providers', [
      ...providers,
      { id, name: preset?.name ?? '自定义厂商', base_url: preset?.base_url ?? '', model: preset?.model ?? '', api_key: '' },
    ])
  }
  const removeProvider = (id: string) => set('ai_providers', providers.filter((p) => p.id !== id))

  async function save(): Promise<boolean> {
    if (!cfg) return false
    try {
      setCfg(await api.saveConfig(cfg))
      setSaved(true)
      return true
    } catch (e) {
      alert(`保存失败: ${e instanceof Error ? e.message : e}`)
      return false
    }
  }

  async function test(provider: 'openai' | 'deepl', id: string) {
    if (!(await save())) return  // 测试前先保存，确保后端用最新配置
    setTests((t) => ({ ...t, [id]: 'testing' }))
    try {
      const r = await api.testTranslate({ provider, provider_id: provider === 'deepl' ? null : id })
      setTests((t) => ({ ...t, [id]: { ok: r.ok, message: r.message } }))
    } catch (e) {
      setTests((t) => ({ ...t, [id]: { ok: false, message: e instanceof Error ? e.message : String(e) } }))
    }
  }

  const testBadge = (id: string) => {
    const r = tests[id]
    if (!r) return null
    if (r === 'testing') return <span className="test-badge testing">测试中…</span>
    return <span className={`test-badge ${r.ok ? 'ok' : 'fail'}`}>{r.ok ? '✓ ' : '✗ '}{r.message}</span>
  }

  return createPortal(
    <div className="dialog-mask" onClick={onClose}>
      <div className="dialog wide" onClick={(e) => e.stopPropagation()}>
        <h3>⚙ 设置</h3>

        {/* ── AI 翻译接口（OpenAI 兼容，支持多厂商）── */}
        <div className="section-head">
          <span>AI 翻译接口（OpenAI 兼容，可添加多家厂商）</span>
        </div>
        {providers.length === 0 && <div className="hint" style={{ marginBottom: 10 }}>尚未添加厂商，点击下方按钮添加。翻译与云端识别都会使用这里的接口。</div>}
        {providers.map((p) => (
          <div key={p.id} className="provider-card">
            <div className="provider-head">
              <input className="provider-name" value={p.name} onChange={(e) => setProvider(p.id, { name: e.target.value })} placeholder="厂商名称" />
              <button className="test-btn" onClick={() => test('openai', p.id)} disabled={tests[p.id] === 'testing'}>测试连接</button>
              <button className="del-btn" title="删除该厂商" onClick={() => removeProvider(p.id)}>✕</button>
            </div>
            <div className="row"><label>Base URL</label>
              <input value={p.base_url} onChange={(e) => setProvider(p.id, { base_url: e.target.value })} placeholder="https://api.example.com/v1" /></div>
            <div className="row"><label>API Key</label>
              <input type="password" value={p.api_key} onChange={(e) => setProvider(p.id, { api_key: e.target.value })} placeholder={p.api_key_set ? '已保存（输入以更换）' : 'sk-...'} /></div>
            <div className="row"><label>模型</label>
              <input value={p.model} onChange={(e) => setProvider(p.id, { model: e.target.value })} placeholder="gpt-4o-mini / deepseek-chat / ..." /></div>
            {testBadge(p.id)}
          </div>
        ))}
        <div className="preset-row">
          <button onClick={() => addProvider()}>+ 空白厂商</button>
          {AI_PRESETS.map((preset) => (
            <button key={preset.name} className="preset-btn" onClick={() => addProvider(preset)}>+ {preset.name}</button>
          ))}
        </div>

        {/* ── DeepL ── */}
        <div className="section-head"><span>DeepL 翻译</span></div>
        <div className="row"><label>DeepL API Key</label>
          <input type="password" value={cfg.deepl_api_key} onChange={(e) => set('deepl_api_key', e.target.value)} placeholder={cfg.deepl_api_key_set ? '已保存（输入以更换）' : 'xxx:fx（免费版以 :fx 结尾）'} />
          <button className="test-btn" onClick={() => test('deepl', 'deepl')} disabled={tests['deepl'] === 'testing'}>测试连接</button></div>
        {testBadge('deepl')}

        {/* ── 语音识别 ── */}
        <div className="section-head"><span>语音识别</span></div>
        <div className="row"><label>识别模型</label>
          <input value={cfg.whisper_model} onChange={(e) => set('whisper_model', e.target.value)} /></div>
        <div className="row"><label>识别设备</label>
          <select value={cfg.whisper_device} onChange={(e) => set('whisper_device', e.target.value)}>
            <option value="auto">自动（优先 GPU）</option>
            <option value="cuda">强制 GPU (CUDA)</option>
            <option value="cpu">强制 CPU</option>
          </select></div>

        <div className="hint">API Key 仅保存在本机配置文件中，不会上传。</div>
        {saved && <div className="hint" style={{ color: 'var(--accent2)' }}>已保存 ✓</div>}
        <div className="actions">
          <button onClick={onClose}>关闭</button>
          <button className="primary" onClick={save}>保存</button>
        </div>
      </div>
    </div>,
    document.body
  )
}
