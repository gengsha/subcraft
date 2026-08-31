// 醒目的任务进度覆盖层：识别/翻译/导出时显示在视频区域中央
import { useStore } from '../store'

export default function ProgressOverlay() {
  const { task, setTask } = useStore()
  if (!task) return null

  // 错误状态：红色卡片 + 可关闭
  if (task.status === 'error') {
    return (
      <div className="progress-overlay">
        <div className="progress-card error">
          <div className="progress-title">✕ {task.label || '任务'}失败</div>
          <div className="progress-detail error-text">{task.error || '未知错误'}</div>
          <button onClick={() => setTask(null)}>关闭</button>
        </div>
      </div>
    )
  }

  if (task.status !== 'running') return null

  const pct = Math.min(100, Math.max(0, Math.round(task.progress * 100)))
  const indeterminate = task.progress <= 0.01

  return (
    <div className="progress-overlay">
      <div className="progress-card">
        <div className="progress-spinner" />
        <div className="progress-title">{task.label || '处理中'}</div>
        <div className="progress-pct">{indeterminate ? '…' : `${pct}%`}</div>
        <div className={`progress-track ${indeterminate ? 'indeterminate' : ''}`}>
          <div className="progress-fill" style={{ width: indeterminate ? '30%' : `${pct}%` }} />
        </div>
        <div className="progress-detail">{task.message || '准备中…'}</div>
      </div>
    </div>
  )
}
