import { API_BASE_URL } from './config';
import type {
  BootstrapResponse,
  HealthResponse,
  MetaResponse,
} from './types';

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`MOMO Studio API request failed with ${response.status}.`);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health');
}

export function getMeta(): Promise<MetaResponse> {
  return requestJson<MetaResponse>('/meta');
}

export async function getBootstrapData(): Promise<BootstrapResponse> {
  const [health, meta] = await Promise.all([getHealth(), getMeta()]);
  return { health, meta };
}
