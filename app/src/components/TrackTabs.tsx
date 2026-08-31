// 字幕轨标签栏 + 双语开关 + 主语言选择
import { LANGUAGES } from '../types'
import { useStore } from '../store'

export default function TrackTabs() {
  const { tracks, activeTrackId, setActiveTrack, removeTrack, bilingual, setBilingual, primaryTrackId, setPrimaryTrack, removeEmptySegments } = useStore()
  const emptyCount = tracks.reduce((n, t) => n + t.segments.filter((s) => !s.text.trim()).length, 0)

  return (
    <div className="track-tabs">
      {tracks.map((t) => (
        <div
          key={t.id}
          className={`track-tab ${t.id === activeTrackId ? 'active' : ''}`}
          onClick={() => setActiveTrack(t.id)}
          title={t.role === 'source' ? '源语言轨 (Source Track)' : '翻译轨 (Translation Track)'}
        >
          <span>{LANGUAGES[t.language] ?? t.language}</span>
          <span className="badge">{t.role === 'source' ? 'SRC' : 'TRN'}:{t.segments.length}</span>
          {bilingual && tracks.length >= 2 && (
            <span
              className="badge"
              title="设为主语言（双语字幕中显示在上方的语言）"
              style={primaryTrackId === t.id ? { color: 'var(--quantum-blue)', borderColor: 'var(--quantum-blue)', fontWeight: 'bold' } : {}}
              onClick={(e) => { e.stopPropagation(); setPrimaryTrack(t.id) }}
            >
              {primaryTrackId === t.id ? '★ 主' : '设为主'}
            </span>
          )}
          <span className="del" title="删除该轨" onClick={(e) => { e.stopPropagation(); removeTrack(t.id) }}>✕</span>
        </div>
      ))}
      {tracks.length >= 2 && (
        <div className="bilingual-toggle">
          <input id="bi" type="checkbox" checked={bilingual} onChange={(e) => setBilingual(e.target.checked)} />
          <label htmlFor="bi">双语对照 [BILINGUAL]</label>
        </div>
      )}
      {emptyCount > 0 && (
        <button
          className="clean-empty"
          title="删除所有文本为空的段落（所有轨道）"
          onClick={removeEmptySegments}
        >
          ⚠ 清理空段 {emptyCount}
        </button>
      )}
      {tracks.length === 0 && (
        <span style={{ color: 'var(--quantum-text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          [TRACK_MATRIX_EMPTY] 请先点击「① 识别字幕」
        </span>
      )}
    </div>
  )
}
