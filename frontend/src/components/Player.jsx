import { useEffect, useRef, useState } from 'react'
import { CircleNotch, Pause, Play } from '@phosphor-icons/react'

const KB_ANIMATIONS = [
  'ken-burns-zoom-in-left',
  'ken-burns-zoom-in-right',
  'ken-burns-zoom-out-left',
  'ken-burns-zoom-out-right',
]

function getImageDuration(images, index) {
  if (index < images.length - 1) {
    return images[index + 1].timestamp_seconds - images[index].timestamp_seconds
  }
  return 30
}

function getImageIndexForTime(images, timeInSeconds) {
  for (let index = images.length - 1; index >= 0; index -= 1) {
    if (timeInSeconds >= images[index].timestamp_seconds) {
      return index
    }
  }
  return 0
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00'
  const totalSeconds = Math.floor(seconds)
  const minutes = Math.floor(totalSeconds / 60)
  const remainingSeconds = String(totalSeconds % 60).padStart(2, '0')
  return `${minutes}:${remainingSeconds}`
}

export default function Player({ images, audioSrc, title }) {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [areImagesReady, setAreImagesReady] = useState(false)
  const [isAudioReady, setIsAudioReady] = useState(false)
  const [audioError, setAudioError] = useState('')
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const audioRef = useRef(null)
  const loadedRef = useRef(0)
  const progressValue = duration > 0 ? Math.min(currentTime, duration) : 0
  const canPlay = areImagesReady && isAudioReady && !audioError

  useEffect(() => {
    loadedRef.current = 0
    setCurrentIndex(0)
    setAreImagesReady(false)
    if (images.length === 0) return

    images.forEach(image => {
      const img = new Image()
      img.onload = () => {
        loadedRef.current += 1
        if (loadedRef.current === images.length) setAreImagesReady(true)
      }
      img.onerror = () => {
        loadedRef.current += 1
        if (loadedRef.current === images.length) setAreImagesReady(true)
      }
      img.src = image.image_url
    })
  }, [images])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    function syncFromAudio() {
      const nextTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0
      const nextDuration = Number.isFinite(audio.duration) ? audio.duration : 0
      setCurrentTime(nextTime)
      setDuration(nextDuration)
      setCurrentIndex(getImageIndexForTime(images, nextTime))
    }

    function handlePlayEvent() {
      setIsPlaying(true)
      syncFromAudio()
    }

    function handlePauseEvent() {
      setIsPlaying(false)
      syncFromAudio()
    }

    function handleEndedEvent() {
      setIsPlaying(false)
      syncFromAudio()
    }

    function handleLoadedState() {
      setAudioError('')
      setIsAudioReady(true)
      syncFromAudio()
    }

    function handleAudioError() {
      setIsAudioReady(false)
      setIsPlaying(false)
      setAudioError('Narration audio could not be loaded.')
    }

    audio.addEventListener('play', handlePlayEvent)
    audio.addEventListener('pause', handlePauseEvent)
    audio.addEventListener('ended', handleEndedEvent)
    audio.addEventListener('timeupdate', syncFromAudio)
    audio.addEventListener('seeked', syncFromAudio)
    audio.addEventListener('canplay', handleLoadedState)
    audio.addEventListener('loadeddata', handleLoadedState)
    audio.addEventListener('loadedmetadata', handleLoadedState)
    audio.addEventListener('durationchange', handleLoadedState)
    audio.addEventListener('error', handleAudioError)

    syncFromAudio()
    if (audio.readyState >= 1) {
      handleLoadedState()
    }

    return () => {
      audio.removeEventListener('play', handlePlayEvent)
      audio.removeEventListener('pause', handlePauseEvent)
      audio.removeEventListener('ended', handleEndedEvent)
      audio.removeEventListener('timeupdate', syncFromAudio)
      audio.removeEventListener('seeked', syncFromAudio)
      audio.removeEventListener('canplay', handleLoadedState)
      audio.removeEventListener('loadeddata', handleLoadedState)
      audio.removeEventListener('loadedmetadata', handleLoadedState)
      audio.removeEventListener('durationchange', handleLoadedState)
      audio.removeEventListener('error', handleAudioError)
    }
  }, [images, audioSrc])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.pause()
    audio.currentTime = 0
    setIsPlaying(false)
    setIsAudioReady(false)
    setAudioError(audioSrc ? '' : 'Narration audio is not available.')
    setCurrentIndex(0)
    setCurrentTime(0)
    setDuration(0)
  }, [audioSrc])

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate
    }
  }, [playbackRate])

  function handlePlay() {
    if (!canPlay) return
    audioRef.current?.play().catch(err => {
      console.error('[Visualang] Audio play failed:', err)
      setIsPlaying(false)
      setAudioError('Narration audio could not be played.')
    })
  }

  function handlePause() {
    audioRef.current?.pause()
  }

  function handleRateChange(event) {
    const rate = parseFloat(event.target.value)
    setPlaybackRate(rate)
    if (audioRef.current) {
      audioRef.current.playbackRate = rate
    }
  }

  function handleSeekChange(event) {
    const audio = audioRef.current
    if (!audio || !canPlay) return

    const nextTime = Number.parseFloat(event.target.value)
    if (!Number.isFinite(nextTime)) return

    audio.currentTime = nextTime
    setCurrentTime(nextTime)
    setCurrentIndex(getImageIndexForTime(images, nextTime))
  }

  return (
    <section className="player-card" aria-label="Illustrated preview player">
      {audioSrc && (
        <audio ref={audioRef} src={audioSrc} preload="metadata" style={{ display: 'none' }} />
      )}

      <div className="player-card__stage">
        {images.map((image, index) => {
          const duration = getImageDuration(images, index)
          const kbClass = KB_ANIMATIONS[index % 4]
          const isActive = index === currentIndex

          return (
            <div
              key={`${image.image_url}${index}`}
              className="player-card__slide"
              style={{
                opacity: isActive ? 1 : 0,
                zIndex: isActive ? 1 : 0,
              }}
            >
              <img
                src={image.image_url}
                alt=""
                className="player-card__image"
                style={{
                  animationName: isPlaying && isActive ? kbClass : 'none',
                  animationDuration: `${duration}s`,
                  animationTimingFunction: 'linear',
                  animationFillMode: 'both',
                  animationPlayState: isPlaying ? 'running' : 'paused',
                }}
              />
            </div>
          )
        })}

        <div className="player-card__vignette" />

        <div className="player-card__controls">
          <div className="player-card__controls-top">
            <div className="player-card__controls-main">
              {!canPlay ? (
                <div className="player-card__loading">
                  {!audioError && (
                    <CircleNotch
                      size={22}
                      aria-hidden="true"
                      style={{ animation: 'spin 1s linear infinite' }}
                    />
                  )}
                  <span
                    className={audioError ? 'player-card__error' : undefined}
                    role={audioError ? 'alert' : undefined}
                  >
                    {audioError || (!areImagesReady ? 'Loading images...' : 'Loading narration...')}
                  </span>
                </div>
              ) : (
                <button
                  type="button"
                  className="player-card__play-button"
                  onClick={isPlaying ? handlePause : handlePlay}
                  disabled={!canPlay}
                  aria-label={isPlaying ? 'Pause narration' : 'Play narration'}
                >
                  {isPlaying ? (
                    <Pause size={22} weight="fill" aria-hidden="true" />
                  ) : (
                    <Play size={22} weight="fill" aria-hidden="true" />
                  )}
                </button>
              )}

              {title && <p className="player-card__title">{title}</p>}
            </div>

            <div className="player-card__controls-side">
              <label className="player-card__rate">
                <span className="sr-only">Playback speed</span>
                <select
                  value={playbackRate}
                  onChange={handleRateChange}
                  className="player-card__select"
                  aria-label="Playback speed"
                >
                  {[0.75, 1, 1.25, 1.5].map(rate => (
                    <option key={rate} value={rate}>
                      {rate}x
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="player-card__timeline">
            <span className="player-card__time" aria-label="Elapsed time">
              {formatTime(progressValue)}
            </span>
            <input
              type="range"
              className="player-card__seek"
              min="0"
              max={duration || 0}
              step="0.1"
              value={progressValue}
              onChange={handleSeekChange}
              disabled={!canPlay || duration === 0}
              aria-label="Seek preview"
            />
            <span className="player-card__time" aria-label="Total duration">
              {formatTime(duration)}
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
