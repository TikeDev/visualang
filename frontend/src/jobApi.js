import { API_URL } from './config.js'

const JOB_HASH_PREFIX = '#/jobs/'

export function parseResumeTokenFromLocation(location) {
  const hash = location?.hash || ''
  if (!hash.startsWith(JOB_HASH_PREFIX)) return null
  const encoded = hash.slice(JOB_HASH_PREFIX.length)
  if (!encoded) return null
  return decodeURIComponent(encoded)
}

export function buildResumeUrl(resumeToken, location = window.location) {
  return `${location.origin}/${JOB_HASH_PREFIX}${encodeURIComponent(resumeToken)}`
}

async function readErrorMessage(response) {
  try {
    const body = await response.json()
    return body.detail || body.error || `HTTP ${response.status}`
  } catch {
    return `HTTP ${response.status}`
  }
}

async function requestJson(path, options) {
  const response = await fetch(`${API_URL}${path}`, options)
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  if (response.status === 204) return null
  return response.json()
}

export async function createJob(input, { signal } = {}) {
  if (input.type === 'youtube') {
    return requestJson('/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'youtube', url: input.url }),
      signal,
    })
  }

  const form = new FormData()
  form.append('file', input.file)
  return requestJson('/jobs/upload', { method: 'POST', body: form, signal })
}

export async function fetchJob(resumeToken, { signal } = {}) {
  const response = await fetch(`${API_URL}/jobs/${resumeToken}`, { signal })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.json()
}

export async function cancelJob(resumeToken) {
  return requestJson(`/jobs/${resumeToken}/cancel`, { method: 'POST' })
}

export async function retryJob(resumeToken) {
  return requestJson(`/jobs/${resumeToken}/retry`, { method: 'POST' })
}

export async function deleteJob(resumeToken) {
  return requestJson(`/jobs/${resumeToken}`, { method: 'DELETE' })
}

export function jobVideoUrl(resumeToken) {
  return `${API_URL}/jobs/${resumeToken}/video`
}

export function jobVideoStreamUrl(resumeToken) {
  return `${API_URL}/jobs/${resumeToken}/video?inline=true`
}

export function jobTranscriptUrl(resumeToken) {
  return `${API_URL}/jobs/${resumeToken}/transcript`
}

export function jobImagesUrl(resumeToken) {
  return `${API_URL}/jobs/${resumeToken}/images`
}
