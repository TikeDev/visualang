import { describe, expect, it } from 'vitest'
import { getJobView } from './jobState.js'

describe('getJobView', () => {
  it('makes cancel secondary while a job is running', () => {
    expect(getJobView({ status: 'running', stage: 'generating_images' })).toMatchObject({
      primary: null,
      secondary: 'cancel',
    })
  })

  it('is queued before any stage has started', () => {
    expect(getJobView({ status: 'queued', stage: 'transcript' })).toMatchObject({
      primary: null,
      secondary: 'cancel',
      label: expect.stringContaining('Queued'),
    })
  })

  it('offers retry for a failed stage without clearing completed data', () => {
    expect(
      getJobView({ status: 'error', stage: 'generating_images', transcript: [{}] })
    ).toMatchObject({ primary: 'retry', preservePreview: true })
  })

  it('offers retry after an interrupted job from a server restart', () => {
    expect(getJobView({ status: 'interrupted', stage: 'export' })).toMatchObject({
      primary: 'retry',
    })
  })

  it('offers continue after a cancelled job and preserves completed work', () => {
    expect(getJobView({ status: 'cancelled', stage: 'generating_images', transcript: [{}] })).toMatchObject({
      primary: 'retry',
      preservePreview: true,
    })
  })

  it('makes video the primary completed action with supporting downloads', () => {
    expect(
      getJobView({
        status: 'done',
        stage: 'export',
        downloads: { video: true, transcript: true, images: true },
      })
    ).toMatchObject({ primary: 'download-video', supportingDownloads: ['transcript', 'images'] })
  })

  it('treats an expired job as terminal with no actions', () => {
    expect(getJobView({ status: 'expired', stage: 'export' })).toMatchObject({
      primary: null,
      secondary: null,
    })
  })
})
