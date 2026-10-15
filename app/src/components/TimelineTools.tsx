// 时间轴工具栏：贴齐镜头切点 / 整体平移 / 修复重叠 / 问题提示（实时检查当前轨）
import { useEffect, useState } from 'react'
import { api, waitTask } from '../api'
import { useStore } from '../store'
import { applyTimeline, playhead } from '../timelineOps'
import type { TimelineInfo } from '../types'

export default function TimelineTools() {
  const { tracks, activeTrackId, videoPath, issues, setIssues, setTask, requestSeek } = useStore()
  const track = tracks.find((t) => t.id === activeTrackId) ?? null
  const [offset, setOffset] = useState('0.3')
  const [fromPlayhead, setFromPlayhead] = useState(false)
  const [cuts, setCuts] = useState<number[] | null>(null)
  const [result, setResult] = useState<TimelineInfo | null>(null)
  const [err, setErr] = useState('')

  // 编辑后 400ms 自动检查当前轨
  useEffect(() => {
    if (!track) { setIssues([]); return }
    const h = setTimeout(() => {
      api.timelineCheck({ segments: track.segments }).then((r) => setIssues(r.issues)).catch(() => {})
    }, 400)
    return () => clearTimeout(h)
  }, [track?.segments])

  useEffect(() => { setCuts(null); setResult(null) }, [videoPath])

  if (!track) return null

  const run = async (fn: () => Promise<void>) => {
    setErr('')
    try { await fn() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }

  const snap = () => run(async () => {
    let found = cuts
    if (!found) {
      const { task_id } = await api.timelineCuts({ video_path: videoPath })
      setTask({ task_id, status: 'running', progress: 0, message: '检测镜头切点', error: null, label: '镜头检测' })
      try {
        const r = await waitTask(task_id, (t) => setTask({ ...t, label: '镜头检测' }))
        found = (r.cuts as number[]) ?? []
      } finally { setTask(null) }
      setCuts(found)
    }
    setResult(await applyTimeline({ op: 'snap', cuts: found }))
  })

  const shift = () => run(async () => {
    const v = parseFloat(offset)
    if (!Number.isFinite(v) || v === 0) throw new Error('请输入非 0 的秒数，正数延后、负数提前')
    setResult(await applyTimeline({ op: 'shift', offset: v, from_time: fromPlayhead ? playhead() : null }))
  })

  const splitAtCut = (index: number, at: number) => run(async () => {
    const info = await applyTimeline({ op: 'split', index, at_time: at })
    setResult((r) => r && { ...r, need_split: r.need_split?.filter((x) => x.index !== index).map((x) => ({ ...x, index: x.index > index ? x.index + 1 : x.index })), synced: info.synced })
  })

  const overlaps = issues.filter((i) => i.type === 'overlap').length

  return (
    <div className="timeline-tools">
      <div className="tt-row">
        <button disabled={!videoPath} title="检测视频镜头切换，让字幕不跨镜头：刚越过切点的收回、离切点很近的贴齐" onClick={snap}>
          ⌖ 贴齐镜头切点{cuts ? `（${cuts.length}）` : ''}
        </button>
        <span className="tt-sep" />
        <label title="正数延后、负数提前（秒）">平移</label>
        <input className="tt-num" value={offset} onChange={(e) => setOffset(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && shift()} />
        <label className="tt-check" title="只平移播放头之后的字幕（如中间插了片头/广告）">
          <input type="checkbox" checked={fromPlayhead} onChange={(e) => setFromPlayhead(e.target.checked)} />从播放头起
        </label>
        <button onClick={shift}>应用</button>
        {overlaps > 0 && (
          <button className="tt-warn" title="把重叠段的结束时间截到下一段开始" onClick={() => run(async () => setResult(await applyTimeline({ op: 'fix_overlaps' })))}>
            修复重叠 {overlaps}
          </button>
        )}
        {issues.length > 0 && (
          <span className="tt-issues" title="点击跳到第一处；列表中标黄的行可悬停查看原因" onClick={() => requestSeek(track.segments[issues[0].index]?.start ?? 0)}>
            ⚠ {issues.length} 处时间轴问题
          </span>
        )}
      </div>
      {err && <div className="tt-msg err">{err}</div>}
      {result && !err && <ResultLine info={result} onSplit={splitAtCut} onClose={() => setResult(null)} />}
    </div>
  )
}

function ResultLine({ info, onSplit, onClose }: { info: TimelineInfo; onSplit: (i: number, at: number) => void; onClose: () => void }) {
  const parts: string[] = []
  if (info.changes) parts.push(`贴齐 ${info.changes.length} 段`)
  if (info.shifted !== undefined) parts.push(`平移 ${info.shifted} 段`)
  if (info.fixed !== undefined) parts.push(`修复重叠 ${info.fixed} 处`)
  if (info.split_at !== undefined) parts.push(`已在 ${info.split_at.toFixed(2)}s 拆分`)
  if (info.synced?.length) parts.push(`已同步 ${info.synced.length} 条对齐轨`)
  return (
    <div className="tt-msg">
      <span>{parts.join('，') || '无改动'}</span>
      {info.need_split?.map((x) => (
        <button key={x.index} className="tt-link" title={x.text} onClick={() => onSplit(x.index, x.cuts[0])}>
          第 {x.index + 1} 段跨镜头 @{x.cuts[0].toFixed(2)}s → 拆分
        </button>
      ))}
      <span className="tt-close" onClick={onClose}>✕</span>
    </div>
  )
}
