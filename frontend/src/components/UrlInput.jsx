import { useRef, useState } from 'react'
import { UploadSimple, Warning, YoutubeLogo } from '@phosphor-icons/react'

const YT_REGEX = /(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([^&?/]+)/
const MAX_FILE_BYTES = 25 * 1024 * 1024
const ALLOWED_EXT = ['.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm']

export default function UrlInput({ onSubmit }) {
  const [mode, setMode] = useState('youtube')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState(null)
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const urlInputRef = useRef(null)
  const fileInputRef = useRef(null)

  function handleUrlChange(event) {
    setUrl(event.target.value)
    setError('')
  }

  function handleFileChange(event) {
    const selectedFile = event.target.files[0]
    if (!selectedFile) return

    const ext = `.${selectedFile.name.split('.').pop().toLowerCase()}`
    if (!ALLOWED_EXT.includes(ext)) {
      setError(`Unsupported file type. Allowed: ${ALLOWED_EXT.join(', ')}`)
      setFile(null)
      fileInputRef.current?.focus()
      return
    }
    if (selectedFile.size > MAX_FILE_BYTES) {
      setError('File exceeds 25 MB limit.')
      setFile(null)
      fileInputRef.current?.focus()
      return
    }

    setError('')
    setFile(selectedFile)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (mode === 'youtube') {
      if (!YT_REGEX.test(url)) {
        setError('Please enter a valid YouTube URL.')
        urlInputRef.current?.focus()
        return
      }
      setIsSubmitting(true)
      try {
        await onSubmit({ type: 'youtube', url })
      } finally {
        setIsSubmitting(false)
      }
      return
    }

    if (!file) {
      setError('Please select an audio file.')
      fileInputRef.current?.focus()
      return
    }

    setIsSubmitting(true)
    try {
      await onSubmit({ type: 'file', file })
    } finally {
      setIsSubmitting(false)
    }
  }

  const isValid = mode === 'youtube' ? YT_REGEX.test(url) : file !== null
  const helpId = 'source-help'
  const errorId = error ? 'source-error' : undefined
  const describedBy = [helpId, errorId].filter(Boolean).join(' ')

  return (
    <section className="source" aria-labelledby="input-title">
      <h1 id="input-title" className="source__title">
        See What You Hear
      </h1>
      <p className="source__sub">
        Paste a YouTube link or upload audio. Visualang illustrates it scene by scene so you can
        follow along in a new language.
      </p>

      <form className="card source__card" onSubmit={handleSubmit}>
        <fieldset className="seg">
          <legend className="sr-only">Choose your source</legend>
          <button
            type="button"
            className={`seg__btn ${mode === 'youtube' ? 'is-active' : ''}`}
            onClick={() => {
              setMode('youtube')
              setError('')
            }}
            aria-pressed={mode === 'youtube'}
          >
            <YoutubeLogo size={18} weight={mode === 'youtube' ? 'fill' : 'regular'} />
            <span>YouTube Link</span>
          </button>
          <button
            type="button"
            className={`seg__btn ${mode === 'file' ? 'is-active' : ''}`}
            onClick={() => {
              setMode('file')
              setError('')
            }}
            aria-pressed={mode === 'file'}
          >
            <UploadSimple size={18} weight={mode === 'file' ? 'fill' : 'regular'} />
            <span>Audio File</span>
          </button>
        </fieldset>

        {mode === 'youtube' ? (
          <div className="field-group">
            <label className="field-label" htmlFor="youtube-url">
              Video URL
            </label>
            <input
              id="youtube-url"
              ref={urlInputRef}
              className="text-input"
              type="url"
              inputMode="url"
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={handleUrlChange}
              aria-describedby={describedBy}
              aria-invalid={error ? 'true' : undefined}
            />
            <p id={helpId} className="field-help">
              Clear spoken audio up to 20 minutes works best.
            </p>
          </div>
        ) : (
          <div className="field-group">
            <span className="field-label" id="audio-upload-label">
              Audio file
            </span>
            <label className="file-picker" htmlFor="audio-file">
              <UploadSimple size={20} />
              <span>{file ? file.name : 'Choose an audio file to upload'}</span>
            </label>
            <input
              id="audio-file"
              ref={fileInputRef}
              className="sr-only"
              type="file"
              accept={ALLOWED_EXT.join(',')}
              onChange={handleFileChange}
              aria-labelledby="audio-upload-label"
              aria-describedby={describedBy}
              aria-invalid={error ? 'true' : undefined}
            />
            <p id={helpId} className="field-help">
              Accepted formats: {ALLOWED_EXT.join(', ')}. Maximum file size: 25 MB.
            </p>
          </div>
        )}

        {error && (
          <p id="source-error" className="field-error" role="alert">
            <Warning size={16} weight="fill" />
            <span>{error}</span>
          </p>
        )}

        <button
          type="submit"
          disabled={!isValid || isSubmitting}
          className="button button--primary source__submit"
        >
          {isSubmitting ? 'Starting…' : 'Visualize'}
        </button>
      </form>
    </section>
  )
}
