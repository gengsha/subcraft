// 预加载：向渲染进程暴露安全的 IPC 与后端地址
const { contextBridge, ipcRenderer } = require('electron')

const portArg = process.argv.find((a) => a.startsWith('--subcraft-port='))
const port = portArg ? portArg.split('=')[1] : '47653'

contextBridge.exposeInMainWorld('subcraft', {
  apiBase: `http://127.0.0.1:${port}`,
  wsBase: `ws://127.0.0.1:${port}`,
  openVideoDialog: () => ipcRenderer.invoke('dialog:openVideo'),
  selectDirDialog: () => ipcRenderer.invoke('dialog:selectDir'),
  saveFileDialog: (defaultName, ext) => ipcRenderer.invoke('dialog:saveFile', defaultName, ext),
})
