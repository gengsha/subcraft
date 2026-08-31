// CDP 冒烟测试：驱动真实 Electron 渲染进程，验证 "探测视频→注入字幕轨→jassub 预览" 全链路
// 用法: node scripts/cdp_smoke_test.mjs <调试端口> <测试视频路径>
const port = process.argv[2] || '9222'
const video = process.argv[3]

if (!video) {
  console.error('缺少测试视频路径参数')
  process.exit(1)
}

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
const page = list.find((t) => t.type === 'page' && (t.url.includes('subcraft') || t.url.includes('index.html')))
if (!page) {
  console.error('FAIL: 找不到渲染进程页面', list.map((t) => t.url))
  process.exit(1)
}

const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
const consoleErrors = []

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data)
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
  if (msg.method === 'Runtime.exceptionThrown') consoleErrors.push(JSON.stringify(msg.params.exceptionDetails).slice(0, 1500))
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') consoleErrors.push(msg.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 400))
}
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const mid = ++id
  pending.set(mid, resolve)
  ws.send(JSON.stringify({ id: mid, method, params }))
  setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); reject(new Error(`timeout: ${method}`)) } }, 30000)
})
await new Promise((r) => { ws.onopen = r })
await send('Runtime.enable')
await send('Page.enable')

const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result.exceptionDetails) throw new Error('页面内执行失败: ' + JSON.stringify(r.result.exceptionDetails).slice(0, 500))
  return r.result.result.value
}

// 1. preload 桥可用
const bridge = await evalJs('typeof window.subcraft === "object" && window.subcraft.apiBase')
console.log('PRELOAD_BRIDGE:', bridge)

// 2. 从渲染进程调后端探测真实视频
const probe = await evalJs(`window.__subcraft_test.api.probe(${JSON.stringify(video)}).then(r=>({d:r.duration,w:r.width,c:r.video_codec})).catch(e=>'ERR:'+e.message)`)
console.log('PROBE:', JSON.stringify(probe))

// 3. 注入字幕轨 → 触发 VideoPlayer 的 ASS 预览 + jassub 渲染
const inject = `(() => {
  const { store } = window.__subcraft_test
  const info = ${JSON.stringify({ path: video, name: 'sample.mp4', duration: 4.6, width: 1280, height: 720, video_codec: 'h264', audio_codec: 'aac', size: 1 })}
  store.getState().setVideo(${JSON.stringify(video)}, info)
  const style = { font_name: 'Microsoft YaHei', font_size: 48, primary_color: '#FFFFFF', outline_color: '#000000', back_color: '#000000', bold: false, italic: false, outline: 2, shadow: 0, alignment: 2, margin_v: 30 }
  store.getState().upsertTrack({ id: 't-zh', language: 'zh', label: '中文', role: 'source', segments: [{ start: 0, end: 4, text: '你好，这是字幕测试。' }], style })
  store.getState().upsertTrack({ id: 't-en', language: 'en', label: 'English', role: 'translation', segments: [{ start: 0, end: 4, text: 'Hello, subtitle test.' }], style: { ...style, font_name: 'Arial', font_size: 32 } })
  return 'injected'
})()`
await evalJs(inject)
await new Promise((r) => setTimeout(r, 6000)) // 等待 debounce + ASS 生成 + jassub 初始化

const render = await evalJs(`(() => {
  const v = document.querySelector('.video-area video')
  const canvas = document.querySelector('.video-area canvas')
  const jc = window.__subcraft_jassub
  return {
    video: !!v, videoSrc: v ? v.src.slice(0, 60) : null, readyState: v ? v.readyState : -1,
    jassubCanvas: !!canvas, canvasSize: canvas ? canvas.width + 'x' + canvas.height : null,
    jassubInstance: !!jc, jassubParent: jc ? jc._canvasParent.className : null,
    trackTabs: document.querySelectorAll('.track-tab').length,
    segRows: document.querySelectorAll('.seg-row').length,
  }
})()`)
console.log('RENDER:', JSON.stringify(render))

// 4. 预览 ASS 接口直接可用
const ass = await evalJs(`window.__subcraft_test.api.previewAss({ tracks: window.__subcraft_test.store.getState().tracks, bilingual: true, primary_id: 't-zh', width: 1280, height: 720 }).then(r => r.ass.split('\\n').filter(l => l.startsWith('Dialogue')).length).catch(e => 'ERR:' + e.message)`)
console.log('PREVIEW_ASS_DIALOGUES:', ass)

// 5. 醒目进度条覆盖层：模拟运行中任务
await evalJs(`window.__subcraft_test.store.getState().setTask({ task_id: 'x', status: 'running', progress: 0.42, message: '识别中 2s / 4s', error: null, label: '识别' })`)
await new Promise((r) => setTimeout(r, 800))
const overlay = await evalJs(`(() => {
  const o = document.querySelector('.progress-overlay .progress-card')
  return o ? {
    pct: o.querySelector('.progress-pct')?.textContent,
    msg: o.querySelector('.progress-detail')?.textContent,
    fillWidth: o.querySelector('.progress-fill')?.style.width,
    spinner: !!o.querySelector('.progress-spinner'),
  } : null
})()`)
console.log('OVERLAY:', JSON.stringify(overlay))

// 6. 错误状态卡片 + 关闭
await evalJs(`window.__subcraft_test.store.getState().setTask({ task_id: 'x', status: 'error', progress: 1, message: '', error: '测试错误', label: '识别' })`)
await new Promise((r) => setTimeout(r, 500))
const errCard = await evalJs(`!!document.querySelector('.progress-card.error')`)
await evalJs(`window.__subcraft_test.store.getState().setTask(null)`)
console.log('ERROR_CARD:', errCard)

// 7. 设置对话框：打开 → 应有 AI 厂商与 DeepL 分区（先记录原配置便于最后还原）
const origProviders = await evalJs(`window.__subcraft_test.api.getConfig().then(c => c.ai_providers)`)
await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('设置'))?.click()`)
await new Promise((r) => setTimeout(r, 600))
const settings = await evalJs(`(() => {
  const heads = [...document.querySelectorAll('.section-head')].map(h => h.textContent.trim())
  const presets = [...document.querySelectorAll('.preset-btn')].map(b => b.textContent.trim())
  return { heads, presetCount: presets.length, testBtns: document.querySelectorAll('.test-btn').length }
})()`)
console.log('SETTINGS:', JSON.stringify(settings))

// 8. 添加一个假厂商并保存 → 配置中应出现且 key 被掩码
await evalJs(`[...document.querySelectorAll('.preset-btn')].find(b => b.textContent.includes('DeepSeek'))?.click()`)
await new Promise((r) => setTimeout(r, 300))
await evalJs(`(() => {
  const cards = document.querySelectorAll('.provider-card')
  const card = cards[cards.length - 1]   // 最后一张卡 = 刚添加的厂商
  const input = card.querySelectorAll('input')[2]   // [名称, BaseURL, APIKey, 模型]
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(input, 'sk-fake-test-key')
  input.dispatchEvent(new Event('input', { bubbles: true }))
})()`)
await evalJs(`[...document.querySelectorAll('.dialog .actions button')].find(b => b.textContent === '保存')?.click()`)
await new Promise((r) => setTimeout(r, 800))
const savedCfg = await evalJs(`window.__subcraft_test.api.getConfig().then(c => ({
  providers: c.ai_providers.map(p => ({ name: p.name, base: p.base_url, keyMasked: p.api_key.startsWith('****'), keySet: !!p.api_key_set })),
}))`)
console.log('SAVED_CFG:', JSON.stringify(savedCfg))

// 9. 测试连接接口：假 key 应失败但接口正常响应；无 key 的 DeepL 应提示未配置
const testAi = await evalJs(`window.__subcraft_test.api.getConfig().then(c => window.__subcraft_test.api.testTranslate({ provider: 'openai', provider_id: c.ai_providers[0].id }))`)
console.log('TEST_AI_FAKE:', JSON.stringify(testAi))
const testDeepl = await evalJs(`window.__subcraft_test.api.testTranslate({ provider: 'deepl' })`)
console.log('TEST_DEEPL_NOKEY:', JSON.stringify(testDeepl))

// 关闭设置对话框并还原原配置
await evalJs(`[...document.querySelectorAll('.dialog .actions button')].find(b => b.textContent === '关闭')?.click()`)
await evalJs(`window.__subcraft_test.api.saveConfig({ ai_providers: ${JSON.stringify(origProviders)} })`)

console.log('CONSOLE_ERRORS:', consoleErrors.length ? consoleErrors : '无')
const pass = bridge && probe && !String(probe).startsWith('ERR') && render.video && render.jassubCanvas && render.jassubInstance && render.jassubParent === 'JASSUB' && render.segRows === 1 && ass >= 1
  && overlay && overlay.pct === '42%' && overlay.fillWidth === '42%' && overlay.spinner && errCard
  && settings.heads.length >= 3 && settings.presetCount >= 5
  && savedCfg.providers.length === 1 && savedCfg.providers[0].keyMasked && savedCfg.providers[0].keySet
  && testAi.ok === false && testDeepl.ok === false && String(testDeepl.message).includes('Key')
  && consoleErrors.length === 0
console.log(pass ? 'SMOKE_TEST_PASS' : 'SMOKE_TEST_FAIL')
process.exit(pass ? 0 : 1)
