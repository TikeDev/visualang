import { CheckCircle, CircleNotch, Clock, Warning } from '@phosphor-icons/react'
import { getJobView } from '../jobState.js'

const STAGE_ORDER = ['transcript', 'concepts', 'generating_images', 'export']
const STAGE_STEP_LABELS = {
  transcript: 'Fetching transcript',
  concepts: 'Extracting concepts',
  generating_images: 'Generating images',
  export: 'Rendering video',
}

function progressLabel(job) {
  const base = STAGE_STEP_LABELS[job.stage] || 'Processing'
  const progress = job.progress
  if (job.stage === 'generating_images' && progress?.total > 0) {
    return `${base.replace('images', 'scene')} ${progress.current} of ${progress.total}`
  }
  return base
}

function StepIcon({ state }) {
  if (state === 'complete') {
    return <CheckCircle size={24} color="var(--color-sage-strong)" weight="fill" />
  }
  if (state === 'active') {
    return (
      <CircleNotch
        size={24}
        color="var(--color-terracotta-strong)"
        style={{ animation: 'spin 1s linear infinite' }}
      />
    )
  }
  return <Clock size={24} color="var(--color-warm-muted)" />
}

function buildSteps(job) {
  const currentIndex = STAGE_ORDER.indexOf(job.stage)
  return STAGE_ORDER.map((stage, index) => {
    let state = 'pending'
    if (index < currentIndex) state = 'complete'
    else if (index === currentIndex) state = 'active'

    const showProgressDetail = state === 'active' && stage === 'generating_images'
    return {
      key: stage,
      label: STAGE_STEP_LABELS[stage],
      state,
      detail: showProgressDetail ? progressLabel(job) : '',
    }
  })
}

export default function JobProgress({ job, onCancel, onRetry, onDelete, headingRef }) {
  const view = getJobView(job)
  const isActive = view.secondary === 'cancel'
  const isFailedOrPaused = view.primary === 'retry'

  if (isActive) {
    const steps = buildSteps(job)
    return (
      <section className="panel panel--loading" aria-labelledby="job-progress-title">
        <div className="panel__copy">
          <p className="eyebrow">Processing Workflow</p>
          <h1 id="job-progress-title" className="panel__title" ref={headingRef} tabIndex="-1">
            Building your illustrated sequence.
          </h1>
          <p className="panel__description">
            Visualang is fetching the transcript, extracting concepts, and preparing the
            generated frames. This page will keep working even if you close the tab — your
            progress link will let you come back to it.
          </p>
        </div>

        {job.title && (
          <div className="loading-screen__context" aria-label="Current source title">
            <p className="loading-screen__context-label">Current source</p>
            <p className="loading-screen__context-title">{job.title}</p>
          </div>
        )}

        <div className="loading-screen__card">
          <div className="sr-only" role="status" aria-live="polite">
            {progressLabel(job)}
          </div>
          <ol className="loading-screen__list">
            {steps.map(step => (
              <li key={step.key} className={`loading-screen__step is-${step.state}`}>
                <span className="loading-screen__icon" aria-hidden="true">
                  <StepIcon state={step.state} />
                </span>
                <span className="loading-screen__body">
                  <span className="loading-screen__label">{step.label}</span>
                  {step.detail && <span className="loading-screen__detail">{step.detail}</span>}
                </span>
              </li>
            ))}
          </ol>

          <div className="job-progress__actions">
            <button type="button" className="button button--secondary" onClick={onCancel}>
              Stop processing
            </button>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="panel panel--job-progress" aria-labelledby="job-progress-title">
      {isFailedOrPaused && (
        <div className="job-progress__paused">
          <h1 id="job-progress-title" className="sr-only" ref={headingRef} tabIndex="-1">
            {view.label}
          </h1>
          {job.error ? (
            <p className="job-progress__error" role="alert">
              <Warning size={18} weight="fill" aria-hidden="true" />
              <span>{job.error}</span>
            </p>
          ) : (
            <p className="job-progress__status">{view.label}</p>
          )}
          {view.preservePreview && (
            <p className="job-progress__preserved">Your completed work is saved.</p>
          )}
        </div>
      )}

      <div className="job-progress__actions">
        {view.primary === 'retry' && (
          <button type="button" className="button button--primary" onClick={onRetry}>
            Continue processing
          </button>
        )}
        {view.secondary === 'delete' && (
          <button type="button" className="button button--secondary" onClick={onDelete}>
            Delete job
          </button>
        )}
      </div>
    </section>
  )
}
