/** Turn any API failure into a sentence a person can act on - always a string.
 *
 * FastAPI reports body-validation problems with `detail` as an ARRAY OF OBJECTS
 * (`[{type, loc, msg, input, ctx}]`), not a string. Rendering that straight into
 * JSX white-screens React with "Objects are not valid as a React child", which
 * is how a mistyped email address took the whole sign-in page down. Anything
 * that shows a server error to a user goes through here.
 */
interface MaybeAxiosError {
  response?: { status?: number; data?: unknown };
  message?: string;
}

/** True when the request never got a response because the NETWORK itself is
 * down (as opposed to a 4xx/5xx the server did answer — or a client timeout,
 * where the server may still be processing and queueing would run it twice).
 * This is what decides whether a chat query may be queued for the offline drain. */
export function isOfflineError(err: unknown): boolean {
  const error = (err ?? {}) as MaybeAxiosError & { isAxiosError?: boolean; code?: string };
  // ECONNABORTED = client timeout: the server may still complete the work, so
  // queueing would double-run it. Only a true network failure queues.
  return error.isAxiosError === true && !error.response && error.code === 'ERR_NETWORK';
}

export function describeApiError(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  const error = (err ?? {}) as MaybeAxiosError;
  const status = error.response?.status;
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;

  if (typeof detail === 'string' && detail.trim()) return flatten(detail);
  if (Array.isArray(detail)) {
    const parts = detail.map(describeValidationItem).filter(Boolean);
    if (parts.length) return flatten(parts.join('; '));
  }
  if (!error.response) return 'Cannot reach the server. Check your connection and try again.';
  if (status === 401) return 'Your session has ended. Please sign in again.';
  if (status === 403) return 'That action is not allowed on this account.';
  if (status === 404) return 'The server could not find what was asked for.';
  if (status === 429) return 'Too many requests just now - please wait a moment and try again.';
  if (status === 502 || status === 503 || status === 504) {
    return 'A service this app depends on is not responding right now.';
  }
  return error.message ? flatten(error.message) : fallback;
}

function describeValidationItem(item: unknown): string {
  const entry = (item ?? {}) as { loc?: unknown[]; msg?: unknown; type?: unknown };
  const field = Array.isArray(entry.loc)
    ? entry.loc.filter((part) => typeof part === 'string').pop()
    : undefined;
  const message = typeof entry.msg === 'string' ? entry.msg : '';
  const label = typeof field === 'string' ? humanize(field) : 'Input';
  if (!message) return '';
  return `${label}: ${message}`;
}

function humanize(field: string): string {
  return field.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

/** The UI speaks these strings out loud, so angle brackets and stacked
 * whitespace from an upstream error page read badly. */
function flatten(text: string): string {
  return text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}
