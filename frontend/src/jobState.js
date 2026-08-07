const STAGE_LABELS = {
  transcript: 'Reading the transcript',
  concepts: 'Finding visual moments',
  generating_images: 'Illustrating scenes',
  export: 'Rendering video',
}

function stageLabel(stage) {
  return STAGE_LABELS[stage] || 'Processing'
}

function hasCompletedWork(job) {
  return Boolean(job.transcript || job.concepts || job.images)
}

/**
 * Maps a backend job payload to the UI's primary/secondary action and copy.
 * Backend statuses: queued, running, cancelled, interrupted, error, done, expired.
 */
export function getJobView(job) {
  const status = job.status

  if (status === 'queued') {
    return {
      label: `Queued - ${stageLabel(job.stage)}`,
      primary: null,
      secondary: 'cancel',
      preservePreview: hasCompletedWork(job),
    }
  }

  if (status === 'running' || status === 'cancel_requested') {
    return {
      label: stageLabel(job.stage),
      primary: null,
      secondary: 'cancel',
      preservePreview: hasCompletedWork(job),
    }
  }

  if (status === 'error' || status === 'interrupted' || status === 'cancelled') {
    return {
      label:
        status === 'error'
          ? `${stageLabel(job.stage)} failed`
          : status === 'interrupted'
            ? 'Interrupted. Your progress is saved'
            : 'Stopped. Your progress is saved',
      primary: 'retry',
      secondary: 'delete',
      preservePreview: hasCompletedWork(job),
    }
  }

  if (status === 'done') {
    const downloads = job.downloads || {}
    const supportingDownloads = ['transcript', 'images'].filter(key => downloads[key])
    return {
      label: 'Done',
      primary: downloads.video ? 'download-video' : null,
      secondary: null,
      supportingDownloads,
      preservePreview: true,
    }
  }

  if (status === 'expired') {
    return {
      label: 'This visualization has expired',
      primary: null,
      secondary: null,
      preservePreview: false,
    }
  }

  return {
    label: 'Unknown status',
    primary: null,
    secondary: null,
    preservePreview: hasCompletedWork(job),
  }
}
