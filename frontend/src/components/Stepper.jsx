const DISPLAY_STAGES = [
  { key: 'source', label: 'Source' },
  { key: 'transcript', label: 'Transcript' },
  { key: 'scenes', label: 'Scenes' },
  { key: 'export', label: 'Video' },
]

function currentDisplayIndex(job) {
  if (job.status === 'done') return 3
  if (job.stage === 'export') return 3
  if (job.stage === 'concepts' || job.stage === 'generating_images') return 2
  if (job.stage === 'transcript') return 1
  return 0
}

export default function Stepper({ job }) {
  const currentIndex = currentDisplayIndex(job)

  return (
    <ol className="stepper" aria-label="Visualization progress">
      {DISPLAY_STAGES.map((stage, index) => {
        let state = 'pending'
        if (job.status === 'done' || index < currentIndex) state = 'complete'
        else if (index === currentIndex) state = 'current'

        return (
          <li
            key={stage.key}
            className={`stepper__step ${state === 'current' ? 'is-current' : ''} ${
              state === 'complete' ? 'is-complete' : ''
            }`}
            data-state={state}
            aria-current={state === 'current' ? 'step' : undefined}
          >
            <span className="stepper__node" aria-hidden="true" />
            <span className="stepper__label">{stage.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
