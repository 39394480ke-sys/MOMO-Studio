import type { PlaybackStatus } from '../../api/types';

const SESSION_LOCK_STATES = new Set(['PREFLIGHTING', 'READY', 'PLAYING', 'PAUSED', 'STOPPING']);

export function playbackLocksLibrary(playback: PlaybackStatus | null): boolean {
  return playback !== null && SESSION_LOCK_STATES.has(playback.state);
}
