import { useEffect, useRef, useState } from 'react'
import {
  CheckCircle,
  CircleNotch,
  FileText,
  ImagesSquare,
  Moon,
  Sun,
  VideoCamera,
  XCircle,
} from '@phosphor-icons/react'
import { API_URL } from './config.js'
import LoadingScreen from './components/LoadingScreen.jsx'
import Player from './components/Player.jsx'
import UrlInput from './components/UrlInput.jsx'

const LOGO_SRC = new URL('../../logos/Visualang-logo.png', import.meta.url).href
const THEME_STORAGE_KEY = 'visualang-theme'
const THEMES = {
  LIGHT: 'light',
  DARK: 'dark',
}
const EXPORT_POLL_INTERVAL_MS = 3000
const EXPORT_POLL_TIMEOUT_MS = 15 * 60 * 1000

const STATES = {
  IDLE: 'idle',
  LOADING_TRANSCRIPT: 'loading_transcript',
  LOADING_CONCEPTS: 'loading_concepts',
  GENERATING_IMAGES: 'generating_images',
  PREVIEW_READY: 'preview_ready',
  EXPORTING: 'exporting',
  EXPORT_FAILED: 'export_failed',
  DONE: 'done',
}

const SAMPLE_IMAGES = [
  {
    timestamp_seconds: 0,
    image_url: 'https://images.unsplash.com/photo-1518020382113-a7e8fc38eac9?w=1024',
  },
  {
    timestamp_seconds: 22,
    image_url: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1024',
  },
  {
    timestamp_seconds: 47,
    image_url: 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1024',
  },
  {
    timestamp_seconds: 71,
    image_url: 'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?w=1024',
  },
  {
    timestamp_seconds: 95,
    image_url: 'https://images.unsplash.com/photo-1501854140801-50d01698950b?w=1024',
  },
]

const DEMO_AUDIO_SRC = 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3'

async function fetchWithRetry(url, options, onRetry) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await fetch(url, options)
      if (!res.ok) {
        let message = `HTTP ${res.status}`
        try {
          const raw = await res.text()
          if (raw) {
            try {
              const parsed = JSON.parse(raw)
              message = parsed.detail || parsed.error || raw
            } catch {
              message = raw
            }
          }
        } catch {
          // ignore body parsing failures and keep the HTTP status message
        }
        throw new Error(message)
      }
      return res
    } catch (err) {
      if (attempt === 3) throw err
      if (attempt === 2) onRetry?.('Connection issue, retrying...')
      await new Promise(resolve => setTimeout(resolve, 1000 * attempt))
    }
  }
}

async function readErrorMessage(response) {
  let message = `HTTP ${response.status}`
  try {
    const raw = await response.text()
    if (raw) {
      try {
        const parsed = JSON.parse(raw)
        message = parsed.detail || parsed.error || raw
      } catch {
        message = raw
      }
    }
  } catch {
    // ignore body parsing failures and keep the HTTP status message
  }
  return message
}

function toAbsoluteUrl(url) {
  if (!url || /^https?:\/\//.test(url)) return url
  return `${API_URL}${url.startsWith('/') ? url : `/${url}`}`
}

function normalizeImages(images) {
  return images.map(image => ({
    ...image,
    image_url: toAbsoluteUrl(image.image_url),
  }))
}

function buildExportPayload(concepts, transcriptData, generatedImages) {
  const exportImages = concepts.map((concept, index) => ({
    timestamp_seconds: concept.timestamp_seconds,
    image_url: generatedImages[index]?.image_url ?? '',
    duration_seconds:
      index < concepts.length - 1
        ? concepts[index + 1].timestamp_seconds - concept.timestamp_seconds
        : 30,
    concept: concept.concept,
  }))

  return {
    audio_path: transcriptData.audio_path,
    images: exportImages,
    transcript: transcriptData.transcript,
  }
}

function transition(setState, state) {
  console.log(`[Visualang] State: ${state}`)
  setState(state)
}

const LOADING_STATES = [
  STATES.LOADING_TRANSCRIPT,
  STATES.LOADING_CONCEPTS,
  STATES.GENERATING_IMAGES,
]

const PREVIEW_STATES = [STATES.PREVIEW_READY, STATES.EXPORTING, STATES.EXPORT_FAILED, STATES.DONE]

function focusElement(element) {
  if (!element) return
  requestAnimationFrame(() => {
    element.focus()
  })
}

function getStoredTheme() {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (storedTheme === THEMES.DARK || storedTheme === THEMES.LIGHT) {
      return storedTheme
    }
  } catch {
    // Ignore storage access failures and fall back to system preference.
  }
  return null
}

function getPreferredTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? THEMES.DARK : THEMES.LIGHT
}

function getInitialTheme() {
  const rootTheme = document.documentElement.dataset.theme
  if (rootTheme === THEMES.DARK || rootTheme === THEMES.LIGHT) {
    return rootTheme
  }
  return getStoredTheme() ?? getPreferredTheme()
}

export default function App() {
  const isDemoMode = new URLSearchParams(window.location.search).has('demo')
  const [appState, setAppState] = useState(isDemoMode ? STATES.PREVIEW_READY : STATES.IDLE)
  const [theme, setTheme] = useState(getInitialTheme)
  const exportPollRef = useRef(null)
  const loadingHeadingRef = useRef(null)
  const previewHeadingRef = useRef(null)
  const errorAlertRef = useRef(null)
  const previousStateRef = useRef(appState)

  const [title, setTitle] = useState('')
  const [images, setImages] = useState([])
  const [audioSrc, setAudioSrc] = useState(null)
  const [exportJobId, setExportJobId] = useState(null)
  const [exportPayload, setExportPayload] = useState(null)
  const [exportErrorMessage, setExportErrorMessage] = useState('')
  const [error, setError] = useState('')
  const [gateWarning, setGateWarning] = useState('')
  const [genProgress, setGenProgress] = useState({ index: 0, total: 0, concept: '' })
  const [retryMsg, setRetryMsg] = useState('')

  function clearExportPoll() {
    if (exportPollRef.current) {
      clearInterval(exportPollRef.current)
      exportPollRef.current = null
    }
  }

  useEffect(() => clearExportPoll, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // Ignore storage access failures and keep the in-memory theme.
    }
  }, [theme])

  useEffect(() => {
    const previousState = previousStateRef.current
    const wasLoading = LOADING_STATES.includes(previousState)
    const isLoading = LOADING_STATES.includes(appState)
    const wasPreview = PREVIEW_STATES.includes(previousState)
    const isPreview = PREVIEW_STATES.includes(appState)

    if (isLoading && !wasLoading) {
      focusElement(loadingHeadingRef.current)
    } else if (isPreview && !wasPreview) {
      focusElement(previewHeadingRef.current)
    }

    previousStateRef.current = appState
  }, [appState])

  useEffect(() => {
    if (error) {
      focusElement(errorAlertRef.current)
    }
  }, [error])

  function resetToIdle() {
    clearExportPoll()
    setAppState(STATES.IDLE)
    setTitle('')
    setImages([])
    setAudioSrc(null)
    setExportJobId(null)
    setExportPayload(null)
    setExportErrorMessage('')
    setError('')
    setGateWarning('')
    setGenProgress({ index: 0, total: 0, concept: '' })
    setRetryMsg('')
    console.log('[Visualang] State: idle (reset)')
  }

  function toggleTheme() {
    setTheme(currentTheme => (currentTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK))
  }

  async function handleSubmit(input) {
    setError('')
    setGateWarning('')
    setRetryMsg('')
    setExportPayload(null)
    setExportErrorMessage('')
    setExportJobId(null)

    transition(setAppState, STATES.LOADING_TRANSCRIPT)
    let transcriptData
    try {
      let res
      if (input.type === 'youtube') {
        res = await fetchWithRetry(
          `${API_URL}/transcript`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_url: input.url }),
          },
          setRetryMsg
        )
      } else {
        const form = new FormData()
        form.append('file', input.file)
        res = await fetchWithRetry(
          `${API_URL}/transcript`,
          { method: 'POST', body: form },
          setRetryMsg
        )
      }
      transcriptData = await res.json()
      setTitle(transcriptData.title)
      setAudioSrc(toAbsoluteUrl(transcriptData.audio_url))
      if (transcriptData.gate?.verdict === 'warn' && transcriptData.gate?.reason) {
        setGateWarning(transcriptData.gate.reason)
      }
      console.log(`[Visualang] Transcript: ${transcriptData.transcript.length} segments`)
    } catch (err) {
      console.error('[Visualang] Transcript failed:', err)
      setError(err.message || 'Failed to fetch transcript. Please try again.')
      setAppState(STATES.IDLE)
      return
    }

    transition(setAppState, STATES.LOADING_CONCEPTS)
    let concepts
    try {
      const res = await fetchWithRetry(
        `${API_URL}/concepts`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transcript: transcriptData.transcript }),
        },
        setRetryMsg
      )
      concepts = await res.json()
      console.log(`[Visualang] Concepts: ${concepts.length}`)
    } catch (err) {
      console.error('[Visualang] Concepts failed:', err)
      setError(err.message || 'Failed to extract concepts. Please try again.')
      setAppState(STATES.IDLE)
      return
    }

    transition(setAppState, STATES.GENERATING_IMAGES)
    let generatedImages = []
    try {
      const response = await fetch(`${API_URL}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ concepts }),
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      if (!response.body) throw new Error('Image stream was empty.')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6))
          if (data.error) throw new Error(data.error)

          if (data.done) {
            generatedImages = normalizeImages(data.images)
            setImages(generatedImages)
            console.log(
              `[Visualang] State: generating_images (${generatedImages.length}/${generatedImages.length})`
            )
          } else {
            setGenProgress({ index: data.index, total: data.total, concept: data.concept })
            console.log(`[Visualang] State: generating_images (${data.index}/${data.total})`)
          }
        }
      }
    } catch (err) {
      console.error('[Visualang] Image generation failed:', err)
      setError(err.message || 'Image generation failed. Please try again.')
      setAppState(STATES.IDLE)
      return
    }

    transition(setAppState, STATES.PREVIEW_READY)
    const nextExportPayload = buildExportPayload(concepts, transcriptData, generatedImages)
    setExportPayload(nextExportPayload)
    kickOffExport(nextExportPayload)
  }

  async function kickOffExport(payload = exportPayload) {
    if (!payload) return

    clearExportPoll()
    setExportErrorMessage('')
    setExportJobId(null)
    transition(setAppState, STATES.EXPORTING)
    try {
      const res = await fetch(`${API_URL}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(await readErrorMessage(res))
      const { job_id } = await res.json()
      setExportJobId(job_id)
      pollExport(job_id)
    } catch (err) {
      console.error('[Visualang] Export start failed:', err)
      setExportErrorMessage('Video export could not start. Retry export from the preview.')
      transition(setAppState, STATES.EXPORT_FAILED)
    }
  }

  async function pollExport(jobId) {
    clearExportPoll()
    const startedAt = Date.now()
    exportPollRef.current = setInterval(async () => {
      if (Date.now() - startedAt > EXPORT_POLL_TIMEOUT_MS) {
        clearExportPoll()
        setExportErrorMessage('Video export took too long. Retry export from the preview.')
        transition(setAppState, STATES.EXPORT_FAILED)
        return
      }

      try {
        const res = await fetch(`${API_URL}/export/${jobId}`)
        if (!res.ok) {
          const detail = await readErrorMessage(res)
          clearExportPoll()
          console.error('[Visualang] Export status failed:', detail)
          setExportErrorMessage(
            res.status === 404
              ? 'Video export status was lost on the server. Retry export from the preview.'
              : 'Video export status could not be checked. Retry export from the preview.'
          )
          transition(setAppState, STATES.EXPORT_FAILED)
          return
        }

        const data = await res.json()
        if (data.status === 'done') {
          clearExportPoll()
          setExportErrorMessage('')
          transition(setAppState, STATES.DONE)
        } else if (data.status === 'error') {
          clearExportPoll()
          console.error('[Visualang] Export error:', data.error)
          setExportErrorMessage(
            'Video export failed after the preview was generated. Retry export to try again.'
          )
          transition(setAppState, STATES.EXPORT_FAILED)
        }
      } catch (err) {
        console.error('[Visualang] Export poll failed:', err)
        clearExportPoll()
        setExportErrorMessage('Video export status could not be checked. Retry export from the preview.')
        transition(setAppState, STATES.EXPORT_FAILED)
      }
    }, EXPORT_POLL_INTERVAL_MS)
  }

  function buildSteps() {
    const stepDefs = [
      { key: STATES.LOADING_TRANSCRIPT, label: 'Fetching transcript' },
      { key: STATES.LOADING_CONCEPTS, label: 'Extracting concepts' },
      { key: STATES.GENERATING_IMAGES, label: 'Generating images' },
    ]
    const order = [STATES.LOADING_TRANSCRIPT, STATES.LOADING_CONCEPTS, STATES.GENERATING_IMAGES]
    const currentIdx = order.indexOf(appState)
    return stepDefs.map((step, index) => {
      let state = 'pending'
      if (index < currentIdx) state = 'complete'
      else if (index === currentIdx) state = 'active'

      let detail = ''
      if (step.key === STATES.GENERATING_IMAGES && appState === STATES.GENERATING_IMAGES) {
        detail =
          genProgress.total > 0
            ? `${genProgress.index} of ${genProgress.total} — "${genProgress.concept}"`
            : ''
      }
      return { label: step.label, state, detail }
    })
  }

  const isLoading = [
    STATES.LOADING_TRANSCRIPT,
    STATES.LOADING_CONCEPTS,
    STATES.GENERATING_IMAGES,
  ].includes(appState)
  const isPreviewState = [
    STATES.PREVIEW_READY,
    STATES.EXPORTING,
    STATES.EXPORT_FAILED,
    STATES.DONE,
  ].includes(appState)
  const hasDownloads = appState === STATES.DONE && exportJobId
  const previewTitle = title || 'Your Visualang preview'
  const liveMessage = (() => {
    if (appState === STATES.LOADING_TRANSCRIPT) {
      return retryMsg || 'Fetching transcript.'
    }
    if (appState === STATES.LOADING_CONCEPTS) {
      return retryMsg || 'Extracting concepts.'
    }
    if (appState === STATES.GENERATING_IMAGES) {
      if (retryMsg) return retryMsg
      if (genProgress.total > 0) {
        return `Generating image ${genProgress.index} of ${genProgress.total}: ${genProgress.concept}.`
      }
      return 'Generating images.'
    }
    if (appState === STATES.PREVIEW_READY) {
      return 'Preview ready.'
    }
    if (appState === STATES.EXPORTING) {
      return 'Rendering your video in the background.'
    }
    if (appState === STATES.EXPORT_FAILED) {
      return exportErrorMessage || 'Export failed. Retry export from the preview.'
    }
    if (appState === STATES.DONE) {
      return hasDownloads ? 'Export complete. Your files are ready below.' : 'Export complete.'
    }
    return ''
  })()

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand" aria-label="Visualang">
          <img src={LOGO_SRC} alt="Visualang" className="app-brand__image" />
        </div>
        <div className="app-header__actions">
          <button
            type="button"
            className="button button--secondary theme-toggle"
            onClick={toggleTheme}
            aria-pressed={theme === THEMES.DARK}
            aria-label={theme === THEMES.DARK ? 'Switch to light mode' : 'Switch to dark mode'}
            title={theme === THEMES.DARK ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            <span className="theme-toggle__icon" aria-hidden="true">
              {theme === THEMES.DARK ? <Sun size={24} weight="fill" /> : <Moon size={24} weight="fill" />}
            </span>
          </button>
          {isPreviewState && (
            <button type="button" className="button button--secondary" onClick={resetToIdle}>
              Create Another Video
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        <div className="sr-only" aria-live="polite" aria-atomic="true">
          {liveMessage}
        </div>

        {error && (
          <div className="notice notice--error" role="alert" ref={errorAlertRef} tabIndex="-1">
            <span>{error}</span>
            <button type="button" className="notice__dismiss" onClick={() => setError('')}>
              Dismiss
            </button>
          </div>
        )}

        {appState === STATES.IDLE && <UrlInput onSubmit={handleSubmit} />}

        {isLoading && (
          <LoadingScreen
            steps={buildSteps()}
            title={title || retryMsg}
            warning={gateWarning}
            headingRef={loadingHeadingRef}
          />
        )}

        {isPreviewState && (
          <section className="stage-view" aria-labelledby="preview-title">
            <div className="stage-view__intro">
              <div className="stage-view__copy">
                <p className="eyebrow">Story Preview</p>
                <h1 id="preview-title" className="stage-view__title" ref={previewHeadingRef} tabIndex="-1">
                  {previewTitle}
                </h1>
                <p className="stage-view__summary">
                  Review the illustrated sequence, listen through the narration, and export the
                  packaged assets when rendering finishes.
                </p>
              </div>
              <div className="stage-view__status">
                {appState === STATES.PREVIEW_READY && (
                  <div className="notice notice--info">
                    Preview is ready while your export status updates in the background.
                  </div>
                )}
                {appState === STATES.EXPORTING && (
                  <div className="notice notice--info">
                    <span className="stage-view__status-indicator">
                      <CircleNotch
                        size={20}
                        weight="bold"
                        aria-hidden="true"
                        className="stage-view__status-spinner"
                      />
                      <span>
                        Rendering your video in the background. You can review the visuals while
                        the export finishes.
                      </span>
                    </span>
                  </div>
                )}
                {appState === STATES.EXPORT_FAILED && (
                  <div className="notice notice--warning">
                    <span className="stage-view__status-indicator">
                      <XCircle
                        size={20}
                        weight="fill"
                        aria-hidden="true"
                        className="stage-view__status-icon"
                      />
                      <span>{exportErrorMessage || 'Video export failed from the current preview.'}</span>
                    </span>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => kickOffExport()}
                    >
                      Retry Export
                    </button>
                  </div>
                )}
                {appState === STATES.DONE && (
                  <div className="notice notice--success">
                    <span className="stage-view__status-indicator">
                      <CheckCircle
                        size={20}
                        weight="fill"
                        aria-hidden="true"
                        className="stage-view__status-icon"
                      />
                      <span>Export complete. Your files are ready below.</span>
                    </span>
                  </div>
                )}
                {gateWarning && (
                  <div className="notice notice--warning">{gateWarning}</div>
                )}
              </div>
            </div>

            <Player
              images={images.length > 0 ? images : SAMPLE_IMAGES}
              audioSrc={isDemoMode ? DEMO_AUDIO_SRC : audioSrc}
              title={title}
            />

            <div className="stage-meta">
              <p className="stage-meta__text">
                Controls stay visible across narrow viewports, and the player scales without
                clipping action areas.
              </p>
            </div>

            {hasDownloads && (
              <div className="stage-actions-section">
                <h2 className="stage-actions__label">Download Files</h2>
                <div className="stage-actions" aria-label="Export downloads">
                  <a
                    href={`${API_URL}/export/${exportJobId}/video`}
                    download="visualang.mp4"
                    className="button button--primary"
                  >
                    <VideoCamera size={20} weight="fill" aria-hidden="true" />
                    <span>Video</span>
                  </a>
                  <a
                    href={`${API_URL}/export/${exportJobId}/transcript`}
                    download="transcript.txt"
                    className="button button--secondary"
                  >
                    <FileText size={20} weight="fill" aria-hidden="true" />
                    <span>Transcript</span>
                  </a>
                  <a
                    href={`${API_URL}/export/${exportJobId}/images`}
                    download="visualang_images.zip"
                    className="button button--secondary"
                  >
                    <ImagesSquare size={20} weight="fill" aria-hidden="true" />
                    <span>Images</span>
                  </a>
                </div>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  )
}
