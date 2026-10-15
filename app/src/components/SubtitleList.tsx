// 字幕段列表：逐条编辑文本与时间码，点击行跳转视频；悬停行尾可拆分 / 与下一段合并 / 删除；有时间轴问题的行标黄
import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { fmtTime, parseTime } from './VideoPlayer'
import { applyTimeline, ISSUE_LABEL, playhead } from '../timelineOps'

export default function SubtitleList() {
  const { tracks, activeTrackId, updateSegment, removeSegment, requestSeek, videoPath, issues } = useStore()
  const track = tracks.find((t) => t.id === activeTrackId) ?? null
  const [currentTime, setCurrentTime] = useState(0)
  const activeRowRef = useRef<HTMLDivElement>(null)

  // 跟随播放进度高亮当前字幕行
  useEffect(() => {
    const video = document.querySelector<HTMLVideoElement>('.video-area video')
    if (!video) return
    const onTime = () => setCurrentTime(video.currentTime)
    video.addEventListener('timeupdate', onTime)
    return () => video.removeEventListener('timeupdate', onTime)
  }, [videoPath])

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [currentTime])

  if (!track) {
    return (
      <div className="list-empty">
        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--quantum-cyan)', marginBottom: 8 }}>
          [TOPOLOGY TIMELINE READY]
        </div>
        导入视频后点击「① 识别字幕」
        <br />
        识别完成后即可在此进行逐帧精确编辑
      </div>
    )
  }

  const issueMap = new Map<number, string[]>()
  for (const it of issues) issueMap.set(it.index, [...(issueMap.get(it.index) ?? []), `${ISSUE_LABEL[it.type] ?? it.type}：${it.detail}`])
  const act = (e: React.MouseEvent, fn: () => Promise<unknown>) => {
    e.stopPropagation()
    fn().catch((err) => alert(err instanceof Error ? err.message : String(err)))
  }

  return (
    <div className="subtitle-list">
      {track.segments.map((seg, i) => {
        const isPlaying = currentTime >= seg.start && currentTime < seg.end
        const warn = issueMap.get(i)
        return (
          <div
            key={i}
            ref={isPlaying ? activeRowRef : undefined}
            className={`seg-row ${isPlaying ? 'active' : ''} ${warn ? 'warn' : ''}`}
            title={warn?.join('\n')}
            onClick={() => requestSeek(seg.start)}
          >
            <TimeInput value={seg.start} onChange={(v) => updateSegment(track.id, i, seg.text, v, seg.end)} />
            <TimeInput value={seg.end} onChange={(v) => updateSegment(track.id, i, seg.text, seg.start, v)} />
            <textarea
              value={seg.text}
              rows={Math.min(3, Math.max(1, seg.text.split('\n').length))}
              placeholder="请输入字幕内容..."
              onChange={(e) => updateSegment(track.id, i, e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
            <div className="seg-actions">
              <button
                title="拆分：播放头在本段内则在播放头处拆，否则在中间的标点/空格处拆（对齐的译文轨同步拆）"
                onClick={(e) => act(e, () => {
                  const t = playhead()
                  return applyTimeline({ op: 'split', index: i, at_time: t > seg.start + 0.05 && t < seg.end - 0.05 ? t : null })
                })}
              >
                ✂
              </button>
              {i < track.segments.length - 1 && (
                <button title="与下一段合并" onClick={(e) => act(e, () => applyTimeline({ op: 'merge', first: i, last: i + 1 }))}>
                  ⤓
                </button>
              )}
              <button className="seg-del" title="删除该段" onClick={(e) => { e.stopPropagation(); removeSegment(track.id, i) }}>
                ✕
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function TimeInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(fmtTime(value))
  const [editing, setEditing] = useState(false)

  useEffect(() => { if (!editing) setText(fmtTime(value)) }, [value, editing])

  return (
    <input
      className="time"
      value={text}
      onFocus={() => setEditing(true)}
      onChange={(e) => setText(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onBlur={() => {
        setEditing(false)
        const v = parseTime(text)
        if (v != null) onChange(v)
        else setText(fmtTime(value))
      }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
    />
  )
}
