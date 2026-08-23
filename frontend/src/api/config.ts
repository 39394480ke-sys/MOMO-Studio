const DEFAULT_API_BASE_URL = '/api/v1';

function removeTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '');
}

export const API_BASE_URL = removeTrailingSlashes(
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL,
);
