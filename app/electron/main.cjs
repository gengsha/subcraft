// Electron 主进程：拉起 Python 后端、创建窗口、提供文件对话框 IPC
const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const { spawn } = require('child_process')
const net = require('net')
const path = require('path')
const fs = require('fs')

let backendProc = null
let backendPort = 47653

function findFreePort() {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port
      srv.close(() => resolve(port))
    })
  })
}

async function waitForBackend(port, timeoutMs = 60000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (res.ok) return true
    } catch {}
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

async function startBackend() {
  backendPort = await findFreePort()
  const root = path.join(__dirname, '..', '..')
  let cmd, args, env = { ...process.env }
  if (app.isPackaged) {
    // 生产：优先用随包的 PyInstaller 后端；Linux 无二进制时回退到系统 python3 + 随包源码
    const res = process.resourcesPath
    const winBin = path.join(res, 'backend', 'subcraft-backend.exe')
    const linuxBin = path.join(res, 'backend', 'subcraft-backend')
    env.SUBCRAFT_TOOLS_DIR = path.join(res, 'tools')
    if (fs.existsSync(winBin)) {
      cmd = winBin
      args = ['--port', String(backendPort)]
    } else if (process.platform !== 'win32' && fs.existsSync(linuxBin)) {
      cmd = linuxBin
      args = ['--port', String(backendPort)]
    } else {
      // Linux 源码回退：需系统 python3 并已安装 backend/requirements.txt
      cmd = process.platform === 'win32' ? 'python' : 'python3'
      args = [path.join(res, 'backend', 'run.py'), '--port', String(backendPort)]
    }
  } else {
    // 开发：项目内 venv 的 Python
    const py = path.join(root, '.venv', 'Scripts', 'python.exe')
    cmd = fs.existsSync(py) ? py : 'python'
    args = [path.join(root, 'backend', 'run.py'), '--port', String(backendPort)]
    env.SUBCRAFT_TOOLS_DIR = path.join(root, 'tools')
  }
  const logFile = path.join(app.getPath('userData'), 'backend.log')
  const logFd = fs.openSync(logFile, 'a')
  backendProc = spawn(cmd, args, { env, cwd: path.dirname(args[0] && args[0].endsWith('run.py') ? args[0] : cmd), stdio: ['ignore', logFd, logFd], windowsHide: true })
  backendProc.on('error', (e) => console.error('backend spawn error:', e.message))
  backendProc.on('exit', (code) => console.log('backend exited:', code, '日志:', logFile))
  const ok = await waitForBackend(backendPort)
  if (!ok) console.error('后端启动超时')
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#16181d',
    title: 'SubCraft 字幕生成器',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      additionalArguments: [`--subcraft-port=${backendPort}`],
    },
  })
  const devUrl = process.env.ELECTRON_RENDERER_URL
  if (devUrl) win.loadURL(devUrl)
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  if (devUrl) win.webContents.openDevTools({ mode: 'detach' })
}

app.whenReady().then(async () => {
  await startBackend()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (backendProc) backendProc.kill()
  if (process.platform !== 'darwin') app.quit()
})

app.on('quit', () => {
  if (backendProc) backendProc.kill()
})

// ---------- IPC：文件对话框 ----------
ipcMain.handle('dialog:openVideo', async () => {
  const r = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [
      { name: '视频文件', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm', 'ts', 'flv', 'wmv', 'm4v'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  })
  return r.canceled ? null : r.filePaths[0]
})

ipcMain.handle('dialog:selectDir', async () => {
  const r = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] })
  return r.canceled ? null : r.filePaths[0]
})

ipcMain.handle('dialog:saveFile', async (_e, defaultName, ext) => {
  const r = await dialog.showSaveDialog({
    defaultPath: defaultName,
    filters: [{ name: ext.toUpperCase(), extensions: [ext] }],
  })
  return r.canceled ? null : r.filePath
})
