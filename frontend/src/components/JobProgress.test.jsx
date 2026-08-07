import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import JobProgress from './JobProgress.jsx'

describe('JobProgress', () => {
  it('announces persisted progress and exposes cancellation', () => {
    render(
      <JobProgress
        job={{
          status: 'running',
          stage: 'generating_images',
          progress: { current: 4, total: 8 },
        }}
        onCancel={vi.fn()}
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent('Illustrating scene 4 of 8')
    expect(screen.getByRole('button', { name: 'Stop' })).toBeEnabled()
  })

  it('presents retry and preserved-work copy after cancellation', () => {
    render(
      <JobProgress
        job={{ status: 'cancelled', stage: 'generating_images', transcript: [{}] }}
        onRetry={vi.fn()}
      />
    )

    expect(screen.getByText('Your progress is saved. Nothing is lost.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('presents retry copy after an interrupted job', () => {
    render(
      <JobProgress
        job={{ status: 'interrupted', stage: 'export', transcript: [{}] }}
        onRetry={vi.fn()}
      />
    )

    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('surfaces a sanitized error and a retry action when a stage fails', () => {
    render(
      <JobProgress
        job={{
          status: 'error',
          stage: 'export',
          error: 'Rendering video failed: FFmpeg could not create the video file.',
        }}
        onRetry={vi.fn()}
      />
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Rendering video failed: FFmpeg could not create the video file.'
    )
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('calls onCancel when the stop action is used', async () => {
    const onCancel = vi.fn()
    const { default: userEvent } = await import('@testing-library/user-event')
    render(
      <JobProgress
        job={{ status: 'running', stage: 'transcript', progress: {} }}
        onCancel={onCancel}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
