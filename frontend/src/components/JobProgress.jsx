import { CircleNotch, Warning } from '@phosphor-icons/react'
import { getJobView } from '../jobState.js'

const STAGE_STEP_LABELS = {
  transcript: 'Reading The Transcript',
  concepts: 'Finding Visual Moments',
  generating_images: 'Illustrating Scenes',
  export: 'Rendering Video',
}

function progressLabel(job) {
  const base = STAGE_STEP_LABELS[job.stage] || 'Processing'
  const progress = job.progress
  if (job.stage === 'generating_images' && progress?.total > 0) {
    return `Illustrating scene ${progress.current} of ${progress.total}`
  }
  return base
}

export default function JobProgress({ job, onCancel, onRetry, onDelete, headingRef }) {
  const view = getJobView(job)
  const isActive = view.secondary === 'cancel'
  const isFailedOrPaused = view.primary === 'retry'

  if (isActive) {
    return (
      <section className="card status-card" aria-labelledby="job-progress-title">
        <h1 id="job-progress-title" className="status-card__title" ref={headingRef} tabIndex="-1">
          Visualizing Your Source
        </h1>

        {job.title && <p className="status-card__source">{job.title}</p>}

        <p className="status-card__stage" role="status" aria-live="polite">
          <CircleNotch size={18} className="status-card__spinner" aria-hidden="true" />
          <span>{progressLabel(job)}</span>
        </p>

        <p className="status-card__note">
          This keeps working even if you close the tab. Your link will bring you back.
        </p>

        <div className="status-card__actions">
          <button type="button" className="button button--secondary" onClick={onCancel}>
            Stop
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="card status-card" aria-labelledby="job-progress-title">
      {isFailedOrPaused && (
        <>
          <h1 id="job-progress-title" className="sr-only" ref={headingRef} tabIndex="-1">
            {view.label}
          </h1>
          {job.error ? (
            <p className="status-card__error" role="alert">
              <Warning size={16} weight="fill" aria-hidden="true" />
              <span>{job.error}</span>
            </p>
          ) : (
            <p className="status-card__note">{view.label}</p>
          )}
          {view.preservePreview && (
            <p className="status-card__note">Your progress is saved.</p>
          )}
        </>
      )}

      <div className="status-card__actions">
        {view.primary === 'retry' && (
          <button type="button" className="button button--primary" onClick={onRetry}>
            Continue
          </button>
        )}
        {view.secondary === 'delete' && (
          <button type="button" className="button button--secondary" onClick={onDelete}>
            Delete
          </button>
        )}
      </div>
    </section>
  )
}
