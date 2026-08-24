import { KeyRound, LockKeyhole, LogOut } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  createLanSecuritySession,
  revokeLanSecuritySession,
} from '../../api/client';
import type { SecuritySessionResponse } from '../../api/types';

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'The LAN security-session request failed.';
}

export function LanSecuritySessionPanel() {
  const [bearerToken, setBearerToken] = useState('');
  const [session, setSession] = useState<SecuritySessionResponse | null>(null);
  const [expired, setExpired] = useState(false);
  const [pending, setPending] = useState<'issue' | 'revoke' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    const remaining = Date.parse(session.expires_at) - Date.now();
    if (remaining <= 0) {
      setExpired(true);
      return;
    }
    const timeout = window.setTimeout(
      () => setExpired(true),
      Math.min(remaining, 2_147_000_000),
    );
    return () => window.clearTimeout(timeout);
  }, [session]);

  const expiryLabel = useMemo(() => {
    if (!session) return null;
    const parsed = new Date(session.expires_at);
    return Number.isNaN(parsed.valueOf()) ? session.expires_at : parsed.toLocaleString();
  }, [session]);

  const canIssue =
    bearerToken.length >= 32 &&
    bearerToken.length <= 512 &&
    !/\s/.test(bearerToken) &&
    pending === null;

  const issue = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canIssue) return;
    setPending('issue');
    setError(null);
    try {
      const issued = await createLanSecuritySession(bearerToken);
      setSession(issued);
      setExpired(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      // The long-lived credential is needed only for the exchange request.
      setBearerToken('');
      setPending(null);
    }
  };

  const revoke = async () => {
    setPending('revoke');
    setError(null);
    try {
      await revokeLanSecuritySession();
      setSession(null);
      setExpired(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="settings-section lan-security" aria-labelledby="lan-security-title">
      <div className="settings-section__heading">
        <p className="section-kicker">Local / LAN access</p>
        <h2 id="lan-security-title">Browser Security Session</h2>
      </div>
      <p className="lan-security__intro">
        Local-only use needs no credential. When an operator explicitly enables LAN,
        exchange the long-lived bearer once for a short-lived HttpOnly cookie. The bearer
        stays only in this field until the request completes and is never stored by the UI.
      </p>

      {!session && (
        <form className="lan-security__form" onSubmit={(event) => void issue(event)}>
          <label>
            <span>LAN bearer token</span>
            <input
              aria-describedby="lan-token-help"
              autoComplete="off"
              disabled={pending !== null}
              maxLength={512}
              onChange={(event) => setBearerToken(event.target.value)}
              spellCheck={false}
              type="password"
              value={bearerToken}
            />
          </label>
          <p id="lan-token-help">
            Never paste this token into a URL, WebSocket address, or browser storage.
          </p>
          <button className="command-button" disabled={!canIssue} type="submit">
            <KeyRound aria-hidden="true" />
            {pending === 'issue' ? 'Exchanging…' : 'Create LAN browser session'}
          </button>
        </form>
      )}

      {session && (
        <div className="real-session-bar lan-security__session" role="status">
          <LockKeyhole aria-hidden="true" />
          <div>
            <span>{expired ? 'Session expired' : 'HttpOnly session active'}</span>
            <strong>Expires {expiryLabel}</strong>
            <small>
              {session.surfaces.join(' · ')} · token unavailable to JavaScript
            </small>
          </div>
          <button
            className="command-button"
            disabled={pending !== null}
            onClick={() => void revoke()}
            type="button"
          >
            <LogOut aria-hidden="true" />
            {pending === 'revoke' ? 'Revoking…' : 'Revoke browser session'}
          </button>
        </div>
      )}

      {error && <p className="real-inline-error" role="alert">{error}</p>}
    </section>
  );
}
