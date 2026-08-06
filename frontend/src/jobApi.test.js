import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildResumeUrl,
  cancelJob,
  createJob,
  deleteJob,
  fetchJob,
  parseResumeTokenFromLocation,
  retryJob,
} from './jobApi.js'

describe('parseResumeTokenFromLocation', () => {
  it('extracts the token from a #/jobs/<token> hash', () => {
    const location = { hash: '#/jobs/abc123.secretvalue' }
    expect(parseResumeTokenFromLocation(location)).toBe('abc123.secretvalue')
  })

  it('returns null when there is no job hash', () => {
    expect(parseResumeTokenFromLocation({ hash: '' })).toBeNull()
    expect(parseResumeTokenFromLocation({ hash: '#/other' })).toBeNull()
  })

  it('decodes percent-encoded tokens', () => {
    const location = { hash: `#/jobs/${encodeURIComponent('abc 123.se cret')}` }
    expect(parseResumeTokenFromLocation(location)).toBe('abc 123.se cret')
  })
})

describe('buildResumeUrl', () => {
  it('builds an encoded private resume link', () => {
    const url = buildResumeUrl('abc123.secret value', { origin: 'https://app.test' })
    expect(url).toBe('https://app.test/#/jobs/abc123.secret%20value')
  })
})

describe('job API calls', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates a youtube job and returns the resume token', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ resume_token: 'job1.secret' }),
    })

    const result = await createJob({ type: 'youtube', url: 'https://youtu.be/x' })

    expect(result.resume_token).toBe('job1.secret')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs'),
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('fetches a job by resume token', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'running', stage: 'concepts' }),
    })

    const job = await fetchJob('job1.secret')

    expect(job.status).toBe('running')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs/job1.secret'),
      expect.any(Object)
    )
  })

  it('returns null for a 404 instead of throwing', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })

    const job = await fetchJob('job1.secret')

    expect(job).toBeNull()
  })

  it('cancels a job', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'cancelled' }),
    })

    const job = await cancelJob('job1.secret')

    expect(job.status).toBe('cancelled')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs/job1.secret/cancel'),
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('retries a job', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 202, json: async () => ({}) })

    await retryJob('job1.secret')

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs/job1.secret/retry'),
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('deletes a job', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 204, json: async () => ({}) })

    await deleteJob('job1.secret')

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs/job1.secret'),
      expect.objectContaining({ method: 'DELETE' })
    )
  })
})
