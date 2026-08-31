import { useEffect, useState } from 'react'
import { api, connectWs } from './api'
import TopBar from './components/TopBar'
import VideoPlayer from './components/VideoPlayer'
import SubtitleList from './components/SubtitleList'
import StylePanel from './components/StylePanel'
import TrackTabs from './components/TrackTabs'
import { useStore } from './store'

// 供自动化冒烟测试驱动 UI（无头验证用）
;(window as unknown as Record<string, unknown>).__subcraft_test = { api, store: useStore }

export default function App() {
  const { setFonts, setTask } = useStore()
  const [sysOk, setSysOk] = useState<{ ffmpeg: boolean; cuda: boolean } | null>(null)

  useEffect(() => {
    api.fonts().then(setFonts).catch(() => {})
    api.systemStatus().then((s) => setSysOk({ ffmpeg: s.ffmpeg_ready, cuda: s.cuda_available })).catch(() => {})
    const close = connectWs((t) => {
      const cur = useStore.getState().task
      if (cur && cur.task_id === t.task_id) setTask({ ...t, label: cur.label })
    })
    return close
  }, [])

  return (
    <div className="app">
      <TopBar sysOk={sysOk} />
      <div className="main">
        <div className="left">
          <VideoPlayer />
          <StylePanel />
        </div>
        <div className="right">
          <TrackTabs />
          <SubtitleList />
        </div>
      </div>
    </div>
  )
}
