// 当前字幕轨的样式编辑面板：字体/字号/颜色/粗斜体/描边/阴影/位置
// 位置有两种模式：对齐+边距（默认）与中心点坐标（拖动字幕或直接填 X/Y）
import { useStore } from '../store'
import type { SubtitleStyle } from '../types'
import { LANGUAGES } from '../types'

const ALIGNMENTS: Record<number, string> = {
  1: '左下 [AN1]', 2: '底部居中 [AN2]', 3: '右下 [AN3]',
  4: '左中 [AN4]', 5: '正中 [AN5]', 6: '右中 [AN6]',
  7: '左上 [AN7]', 8: '顶部居中 [AN8]', 9: '右上 [AN9]',
}

export default function StylePanel() {
  const { tracks, activeTrackId, updateTrack, fonts } = useStore()
  const track = tracks.find((t) => t.id === activeTrackId)

  if (!track) {
    return (
      <div className="style-panel">
        <div className="style-hint">请在右侧选择或导入字幕轨后配置排版参数</div>
      </div>
    )
  }

  const setStyle = (patch: Partial<SubtitleStyle>) => updateTrack(track.id, { style: { ...track.style, ...patch } })
  const fontNames = Object.keys(fonts)
  const posMode = track.style.pos_x != null && track.style.pos_y != null

  return (
    <div className="style-panel">
      <h4>
        <span className="tag">{LANGUAGES[track.language] ?? track.language}</span>
      </h4>
      <div className="style-grid">
        <div className="style-item">
          <label>字体</label>
          <select value={track.style.font_name} onChange={(e) => setStyle({ font_name: e.target.value })} style={{ maxWidth: 170 }}>
            {!fontNames.includes(track.style.font_name) && <option value={track.style.font_name}>{track.style.font_name}</option>}
            {fontNames.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div className="style-item">
          <label>字号</label>
          <input type="number" min={8} max={200} value={track.style.font_size} onChange={(e) => setStyle({ font_size: +e.target.value || 48 })} />
        </div>
        <div className="style-item">
          <label>主色</label>
          <input type="color" value={track.style.primary_color} onChange={(e) => setStyle({ primary_color: e.target.value })} title={track.style.primary_color} />
        </div>
        <div className="style-item">
          <label>描边色</label>
          <input type="color" value={track.style.outline_color} onChange={(e) => setStyle({ outline_color: e.target.value })} title={track.style.outline_color} />
        </div>
        <div className="style-item">
          <label>描边宽</label>
          <input type="number" min={0} max={10} step={0.5} value={track.style.outline} onChange={(e) => setStyle({ outline: +e.target.value })} />
        </div>
        <div className="style-item">
          <label>阴影</label>
          <input type="number" min={0} max={10} step={0.5} value={track.style.shadow} onChange={(e) => setStyle({ shadow: +e.target.value })} />
        </div>
        {posMode ? (
          <>
            <div className="style-item">
              <label>X 坐标</label>
              <input type="number" min={0} max={8000} value={Math.round(track.style.pos_x!)} onChange={(e) => setStyle({ pos_x: +e.target.value })} />
            </div>
            <div className="style-item">
              <label>Y 坐标</label>
              <input type="number" min={0} max={8000} value={Math.round(track.style.pos_y!)} onChange={(e) => setStyle({ pos_y: +e.target.value })} />
            </div>
            <div className="style-item">
              <button className="pos-reset" title="清除中心点坐标，回到对齐/边距布局" onClick={() => setStyle({ pos_x: null, pos_y: null })}>
                ↺ 恢复默认布局
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="style-item">
              <label>对齐</label>
              <select value={track.style.alignment} onChange={(e) => setStyle({ alignment: +e.target.value })}>
                {Object.entries(ALIGNMENTS).map(([v, name]) => <option key={v} value={v}>{name}</option>)}
              </select>
            </div>
            <div className="style-item">
              <label>垂直边距</label>
              <input type="number" min={0} max={2000} value={track.style.margin_v} onChange={(e) => setStyle({ margin_v: +e.target.value })} />
            </div>
            <div className="style-item">
              <label>左边距</label>
              <input type="number" min={0} max={4000} value={track.style.margin_l} onChange={(e) => setStyle({ margin_l: +e.target.value })} />
            </div>
            <div className="style-item">
              <label>右边距</label>
              <input type="number" min={0} max={4000} value={track.style.margin_r} onChange={(e) => setStyle({ margin_r: +e.target.value })} />
            </div>
          </>
        )}
        <div className="style-item">
          <input id={`b-${track.id}`} type="checkbox" checked={track.style.bold} onChange={(e) => setStyle({ bold: e.target.checked })} />
          <label htmlFor={`b-${track.id}`}>粗体</label>
          <input id={`i-${track.id}`} type="checkbox" checked={track.style.italic} onChange={(e) => setStyle({ italic: e.target.checked })} />
          <label htmlFor={`i-${track.id}`}>斜体</label>
        </div>
      </div>
      <div className="style-hint">
        {posMode
          ? `[COORDINATE: POS(${Math.round(track.style.pos_x!)}, ${Math.round(track.style.pos_y!)})] 拖动视频画面可实时更新中心点坐标`
          : '提示：直接在视频画面上按住拖动字幕进入精准中心点定位；「恢复默认布局」可回到对齐/边距模式'}
      </div>
    </div>
  )
}
