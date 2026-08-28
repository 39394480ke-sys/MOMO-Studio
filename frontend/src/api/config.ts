const DEFAULT_API_BASE_URL = '/api/v1';

function removeTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '');
}

export const API_BASE_URL = removeTrailingSlashes(
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL,
);

export function robotWebSocketUrl(location: Location = window.location): string {
  const base = new URL(API_BASE_URL || '/', location.href);
  const socket = new URL(`${removeTrailingSlashes(base.pathname)}/ws/robot`, base.origin);
  socket.protocol = socket.protocol === 'https:' ? 'wss:' : 'ws:';
  return socket.toString();
}
