import type { schemas } from './contract.generated';
import { validate } from './validation';
export const prefix = '/api/console/v1';
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}
export async function read<T>(path: string, name: keyof typeof schemas, signal?: AbortSignal): Promise<T> {
  const response = await fetch(prefix + path, { credentials: 'same-origin', cache: 'no-store',
    signal: signal ?? AbortSignal.timeout(4000), redirect: 'error' });
  if (!response.ok) throw new ApiError(response.status, 'read_failed');
  const text = await response.text();
  if (text.length > 250_000) throw Error('response_size_limit');
  return validate<T>(name, JSON.parse(text));
}
export async function post<T>(path: string, name: keyof typeof schemas, data: object, csrf: string): Promise<T> {
  const response = await fetch(prefix + path, { method: 'POST', credentials: 'same-origin',
    cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(4000),
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, csrf }) });
  if (!response.ok) throw new ApiError(response.status, 'mutation_failed');
  return validate<T>(name, await response.json());
}
