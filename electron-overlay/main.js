const { app, BrowserWindow, ipcMain, globalShortcut, screen, desktopCapturer, nativeImage } = require('electron')
const path = require('path')

const isDev = process.env.NODE_ENV === 'development' || process.env.ELECTRON_DEV === '1'

let mainWindow

function createWindow() {
  const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize

  mainWindow = new BrowserWindow({
    width: 380,
    height: 520,
    // Start in bottom-right corner, WoW-friendly position
    x: screenWidth - 400,
    y: screenHeight - 560,
    frame: false,           // No OS chrome — we draw our own title bar
    transparent: true,      // Enables the translucent background
    alwaysOnTop: true,      // Stays above WoW
    resizable: true,
    skipTaskbar: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Keep always-on-top even when WoW goes fullscreen (screen-saver level)
  mainWindow.setAlwaysOnTop(true, 'screen-saver')

  if (isDev) {
    mainWindow.loadURL('http://localhost:5174')
    // Uncomment to open DevTools in dev mode:
    // mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  createWindow()

  // Global hotkey: Ctrl+Shift+R — toggle overlay visibility
  globalShortcut.register('CommandOrControl+Shift+R', () => {
    if (!mainWindow) return
    if (mainWindow.isVisible()) {
      mainWindow.hide()
    } else {
      mainWindow.show()
      mainWindow.focus()
    }
  })

  // Global hotkey: Ctrl+Shift+S — trigger screenshot from anywhere
  globalShortcut.register('CommandOrControl+Shift+S', () => {
    if (mainWindow) {
      mainWindow.webContents.send('trigger-screenshot')
      mainWindow.show()
      mainWindow.focus()
    }
  })
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

// ── IPC Handlers ──────────────────────────────────────────────────────────────

// Window dragging (frameless window needs manual drag)
ipcMain.on('window-drag-start', () => {})

// Minimize
ipcMain.on('window-minimize', () => {
  mainWindow?.minimize()
})

// Close / hide (we hide rather than quit so hotkey can bring it back)
ipcMain.on('window-hide', () => {
  mainWindow?.hide()
})

// Quit completely
ipcMain.on('window-quit', () => {
  app.quit()
})

// Opacity change
ipcMain.on('set-opacity', (_, value) => {
  mainWindow?.setOpacity(value)
})

// Screenshot: capture the primary display at a reduced resolution.
// We capture at 1024×576 — the backend will resize+JPEG-compress further.
// Keeping it small here means less data sent over localhost and faster encoding.
// For a 3440×1440 ultrawide, 1024px wide is still plenty for vision analysis.
ipcMain.handle('capture-screenshot', async () => {
  try {
    // Briefly hide the overlay so it doesn't appear in the screenshot
    const wasVisible = mainWindow?.isVisible()
    mainWindow?.hide()

    // Small delay to let WoW re-render without the overlay
    await new Promise((r) => setTimeout(r, 200))

    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 1024, height: 576 },
    })

    const primary = sources[0]
    // toDataURL() returns PNG by default; we request JPEG at quality 80
    // to further shrink the payload sent to the backend
    const dataURL = primary?.thumbnail?.toJPEG(80)
      ? `data:image/jpeg;base64,${primary.thumbnail.toJPEG(80).toString('base64')}`
      : primary?.thumbnail?.toDataURL()

    // Restore overlay
    if (wasVisible) mainWindow?.show()

    return dataURL || null
  } catch (err) {
    mainWindow?.show()
    return null
  }
})

// Click-through toggle: when enabled, mouse clicks pass through to WoW
ipcMain.on('set-click-through', (_, enabled) => {
  mainWindow?.setIgnoreMouseEvents(enabled, { forward: true })
})
