import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, ImagesSquare, Moon, Sun, VideoCamera } from '@phosphor-icons/react'
import { API_URL } from './config.js'
import {
  buildResumeUrl,
  cancelJob,
  createJob,
  deleteJob,
  fetchJob,
  jobImagesUrl,
  jobTranscriptUrl,
  jobVideoUrl,
  parseResumeTokenFromLocation,
  retryJob,
} from './jobApi.js'
import JobProgress from './components/JobProgress.jsx'
import Player from './components/Player.jsx'
import UrlInput from './components/UrlInput.jsx'

const LOGO_SRC = new URL('../../logos/Visualang-logo.png', import.meta.url).href
const THEME_STORAGE_KEY = 'visualang-theme'
const THEMES = {
  LIGHT: 'light',
  DARK: 'dark',
}
const POLL_INTERVAL_MS = 3000
const TERMINAL_STATUSES = new Set(['done', 'expired'])
const PAUSED_STATUSES = new Set(['error', 'cancelled', 'interrupted'])

function toAbsoluteUrl(url) {
  if (!url || /^https?:\/\//.test(url)) return url
  return `${API_URL}${url.startsWith('/') ? url : `/${url}`}`
}

function normalizeImages(images) {
  return (images || []).map(image => ({
    ...image,
    image_url: toAbsoluteUrl(image.image_url),
  }))
}

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
  const [theme, setTheme] = useState(getInitialTheme)
  const [resumeToken, setResumeToken] = useState(() =>
    parseResumeTokenFromLocation(window.location)
  )
  const [job, setJob] = useState(null)
  const [isRestoring, setIsRestoring] = useState(() => Boolean(resumeToken))
  const [error, setError] = useState('')
  const [imageLoadError, setImageLoadError] = useState('')

  const pollRef = useRef(null)
  const loadingHeadingRef = useRef(null)
  const previewHeadingRef = useRef(null)
  const errorAlertRef = useRef(null)
  const wasPreviewRef = useRef(false)
  const wasJobRef = useRef(false)

  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => clearPoll, [clearPoll])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // Ignore storage access failures and keep the in-memory theme.
    }
  }, [theme])

  const pollJob = useCallback(
    token => {
      clearPoll()

      async function tick() {
        try {
          const nextJob = await fetchJob(token)
          if (nextJob === null) {
            setJob(current => (current ? { ...current, status: 'expired' } : current))
            setIsRestoring(false)
            return
          }
          setJob(nextJob)
          setIsRestoring(false)
          if (!TERMINAL_STATUSES.has(nextJob.status) && !PAUSED_STATUSES.has(nextJob.status)) {
            pollRef.current = setTimeout(tick, POLL_INTERVAL_MS)
          }
        } catch (err) {
          console.error('[Visualang] Job poll failed:', err)
          pollRef.current = setTimeout(tick, POLL_INTERVAL_MS)
        }
      }

      tick()
    },
    [clearPoll]
  )

  useEffect(() => {
    if (!resumeToken) return
    window.history.replaceState(null, '', buildResumeUrl(resumeToken))
    pollJob(resumeToken)
    return clearPoll
  }, [resumeToken, pollJob, clearPoll])

  useEffect(() => {
    const isPreview = Boolean(job && (job.images?.length || job.status === 'done'))
    if (isPreview && !wasPreviewRef.current) {
      focusElement(previewHeadingRef.current)
    } else if (job && !wasJobRef.current) {
      focusElement(loadingHeadingRef.current)
    }
    wasPreviewRef.current = isPreview
    wasJobRef.current = Boolean(job)
  }, [job])

  useEffect(() => {
    if (error) {
      focusElement(errorAlertRef.current)
    }
  }, [error])

  function toggleTheme() {
    setTheme(currentTheme => (currentTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK))
  }

  function resetToIdle() {
    clearPoll()
    setResumeToken(null)
    setJob(null)
    setIsRestoring(false)
    setError('')
    setImageLoadError('')
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }

  async function handleSubmit(input) {
    setError('')
    setImageLoadError('')
    setIsRestoring(true)
    try {
      const { resume_token } = await createJob(input)
      setResumeToken(resume_token)
    } catch (err) {
      console.error('[Visualang] Job creation failed:', err)
      setError(err.message || 'Could not start this job.')
      setIsRestoring(false)
    }
  }

  async function handleCancel() {
    if (!resumeToken) return
    try {
      const updated = await cancelJob(resumeToken)
      setJob(updated)
    } catch (err) {
      console.error('[Visualang] Cancel failed:', err)
      setError(err.message || 'Could not cancel this job.')
    }
  }

  async function handleRetry() {
    if (!resumeToken) return
    try {
      await retryJob(resumeToken)
      pollJob(resumeToken)
    } catch (err) {
      console.error('[Visualang] Retry failed:', err)
      setError(err.message || 'Could not retry this job.')
    }
  }

  async function handleDelete() {
    if (!resumeToken) return
    try {
      await deleteJob(resumeToken)
    } catch (err) {
      console.error('[Visualang] Delete failed:', err)
    }
    resetToIdle()
  }

  function handleImageError(image) {
    setImageLoadError(`A scene image failed to load (timestamp ${image.timestamp_seconds}s).`)
  }

  const isActive = job && !TERMINAL_STATUSES.has(job.status) && !PAUSED_STATUSES.has(job.status)
  const isPausedOrFailed = job && PAUSED_STATUSES.has(job.status)
  const images = normalizeImages(job?.images)
  const hasPreview = Boolean(job && (images.length > 0 || job.status === 'done'))
  const previewTitle = job?.title || 'Your Visualang preview'
  const hasDownloads = job?.status === 'done'
  const audioSrc = job?.audio_url ? toAbsoluteUrl(job.audio_url) : null

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
          {job && (
            <button type="button" className="button button--secondary" onClick={resetToIdle}>
              Create Another Video
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        {error && (
          <div className="notice notice--error" role="alert" ref={errorAlertRef} tabIndex="-1">
            <span>{error}</span>
            <button type="button" className="notice__dismiss" onClick={() => setError('')}>
              Dismiss
            </button>
          </div>
        )}

        {!job && !isRestoring && <UrlInput onSubmit={handleSubmit} />}

        {isRestoring && !job && (
          <div className="notice notice--info" role="status">
            Setting things up...
          </div>
        )}

        {job && (
          <>
            {(isActive || isPausedOrFailed) && (
              <JobProgress
                job={job}
                onCancel={handleCancel}
                onRetry={handleRetry}
                onDelete={handleDelete}
                headingRef={loadingHeadingRef}
              />
            )}

            {job.gate?.reason && <div className="notice notice--warning">{job.gate.reason}</div>}

            {hasPreview && (
              <section className="stage-view" aria-labelledby="preview-title">
                <div className="stage-view__intro">
                  <div className="stage-view__copy">
                    <p className="eyebrow">Story Preview</p>
                    <h1
                      id="preview-title"
                      className="stage-view__title"
                      ref={previewHeadingRef}
                      tabIndex="-1"
                    >
                      {previewTitle}
                    </h1>
                    <p className="stage-view__summary">
                      Review the illustrated sequence, listen through the narration, and export
                      the packaged assets when rendering finishes.
                    </p>
                  </div>
                </div>

                {imageLoadError && <div className="notice notice--warning">{imageLoadError}</div>}

                <Player
                  images={images}
                  audioSrc={audioSrc}
                  title={job.title}
                  onImageError={handleImageError}
                />

                {hasDownloads && (
                  <div className="stage-actions-section">
                    <h2 className="stage-actions__label">Download Files</h2>
                    <div className="stage-actions" aria-label="Export downloads">
                      <a
                        href={jobVideoUrl(resumeToken)}
                        download="visualang.mp4"
                        className="button button--primary"
                      >
                        <VideoCamera size={20} weight="fill" aria-hidden="true" />
                        <span>Video</span>
                      </a>
                      <a
                        href={jobTranscriptUrl(resumeToken)}
                        download="transcript.txt"
                        className="button button--secondary"
                      >
                        <FileText size={20} weight="fill" aria-hidden="true" />
                        <span>Transcript</span>
                      </a>
                      <a
                        href={jobImagesUrl(resumeToken)}
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
          </>
        )}
      </main>
    </div>
  )
}
