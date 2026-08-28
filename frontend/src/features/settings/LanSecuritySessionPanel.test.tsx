import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createLanSecuritySession,
  revokeLanSecuritySession,
} from '../../api/client';
import { LanSecuritySessionPanel } from './LanSecuritySessionPanel';

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  createLanSecuritySession: vi.fn(),
  revokeLanSecuritySession: vi.fn(),
}));

const bearer = 'lan-browser-session-token-material-0123456789';

function memoryStorageSpy(): Storage {
  return {
    clear: vi.fn(),
    getItem: vi.fn(() => null),
    key: vi.fn(() => null),
    length: 0,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  };
}

beforeEach(() => {
  vi.mocked(createLanSecuritySession).mockReset();
  vi.mocked(revokeLanSecuritySession).mockReset();
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: memoryStorageSpy(),
  });
  Object.defineProperty(window, 'sessionStorage', {
    configurable: true,
    value: memoryStorageSpy(),
  });
});

describe('LanSecuritySessionPanel', () => {
  it('keeps the bearer only in component memory and shows expiry plus revoke', async () => {
    vi.mocked(createLanSecuritySession).mockResolvedValue({
      principal_id: 'operator',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-08-24T01:05:00Z',
      surfaces: ['REST', 'CONTROL', 'WEBSOCKET', 'VISION'],
    });
    vi.mocked(revokeLanSecuritySession).mockResolvedValue();
    render(<LanSecuritySessionPanel />);

    const input = screen.getByLabelText('局域网 Bearer Token');
    fireEvent.change(input, { target: { value: bearer } });
    fireEvent.click(screen.getByRole('button', { name: /创建局域网浏览器会话/ }));

    await waitFor(() => expect(createLanSecuritySession).toHaveBeenCalledWith(bearer));
    expect(await screen.findByText('HttpOnly 会话已生效')).toBeVisible();
    expect(screen.getByText(/到期时间/)).toBeVisible();
    expect(screen.getByText(/JavaScript 无法读取/)).toBeVisible();
    expect(screen.queryByDisplayValue(bearer)).not.toBeInTheDocument();
    expect(window.localStorage.setItem).not.toHaveBeenCalled();
    expect(window.sessionStorage.setItem).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /撤销浏览器会话/ }));
    await waitFor(() => expect(revokeLanSecuritySession).toHaveBeenCalledTimes(1));
    expect(await screen.findByLabelText('局域网 Bearer Token')).toHaveValue('');
  });

  it('clears a rejected bearer and renders only the safe error', async () => {
    vi.mocked(createLanSecuritySession).mockRejectedValue(new Error('Invalid LAN credential'));
    render(<LanSecuritySessionPanel />);

    const input = screen.getByLabelText('局域网 Bearer Token');
    fireEvent.change(input, { target: { value: bearer } });
    fireEvent.click(screen.getByRole('button', { name: /创建局域网浏览器会话/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid LAN credential');
    expect(input).toHaveValue('');
    expect(screen.queryByText(bearer)).not.toBeInTheDocument();
    expect(window.localStorage.setItem).not.toHaveBeenCalled();
    expect(window.sessionStorage.setItem).not.toHaveBeenCalled();
  });
});
