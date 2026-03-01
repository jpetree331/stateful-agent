const { contextBridge, ipcRenderer } = require('electron')

// Expose a safe, typed API to the renderer (React app)
contextBridge.exposeInMainWorld('electronAPI', {
  // Window controls
  minimize: () => ipcRenderer.send('window-minimize'),
  hide: () => ipcRenderer.send('window-hide'),
  quit: () => ipcRenderer.send('window-quit'),

  // Opacity (0.0 – 1.0)
  setOpacity: (value) => ipcRenderer.send('set-opacity', value),

  // Screenshot: resolves to a base64 data URL string or null
  captureScreenshot: () => ipcRenderer.invoke('capture-screenshot'),

  // Click-through mode (mouse passes to WoW)
  setClickThrough: (enabled) => ipcRenderer.send('set-click-through', enabled),

  // Listen for hotkey-triggered screenshot from main process
  onTriggerScreenshot: (callback) => {
    ipcRenderer.on('trigger-screenshot', callback)
    return () => ipcRenderer.removeListener('trigger-screenshot', callback)
  },
})
