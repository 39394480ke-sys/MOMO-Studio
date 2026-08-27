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
  return '局域网安全会话请求失败。';
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
    return Number.isNaN(parsed.valueOf()) ? session.expires_at : parsed.toLocaleString('zh-CN');
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
        <p className="section-kicker">本机 / 局域网访问</p>
        <h2 id="lan-security-title">浏览器安全会话</h2>
      </div>
      <p className="lan-security__intro">
        仅在本机使用时不需要凭证。明确启用局域网访问后，可用长期 Bearer Token
        换取短期 HttpOnly Cookie。Token 只在请求期间保留在此输入框中，界面不会存储。
      </p>

      {!session && (
        <form className="lan-security__form" onSubmit={(event) => void issue(event)}>
          <label>
            <span>局域网 Bearer Token</span>
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
            不要把此 Token 粘贴到网址、WebSocket 地址或浏览器存储中。
          </p>
          <button className="command-button" disabled={!canIssue} type="submit">
            <KeyRound aria-hidden="true" />
            {pending === 'issue' ? '正在交换…' : '创建局域网浏览器会话'}
          </button>
        </form>
      )}

      {session && (
        <div className="real-session-bar lan-security__session" role="status">
          <LockKeyhole aria-hidden="true" />
          <div>
            <span>{expired ? '会话已过期' : 'HttpOnly 会话已生效'}</span>
            <strong>到期时间：{expiryLabel}</strong>
            <small>
              {session.surfaces.join(' · ')} · JavaScript 无法读取 Token
            </small>
          </div>
          <button
            className="command-button"
            disabled={pending !== null}
            onClick={() => void revoke()}
            type="button"
          >
            <LogOut aria-hidden="true" />
            {pending === 'revoke' ? '正在撤销…' : '撤销浏览器会话'}
          </button>
        </div>
      )}

      {error && <p className="real-inline-error" role="alert">{error}</p>}
    </section>
  );
}
