import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { MotionCommandStatus } from '../../api/types';
import { CommandStatusPanel } from './CommandStatusPanel';

describe('CommandStatusPanel', () => {
  it('renders repeated preflight check names without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const command: MotionCommandStatus = {
      command_id: '00000000-0000-4000-8000-000000000001',
      state: 'COMPLETED',
      progress: 1,
      preflight: {
        accepted: true,
        checks: [
          { name: 'joint_set', passed: true, detail: 'Requested joint is enabled' },
          { name: 'joint_set', passed: true, detail: 'Target matches the enabled joint set' },
        ],
        warnings: [],
      },
    };

    render(
      <CommandStatusPanel
        command={command}
        commandError={null}
        fkError={null}
        rejectedPreflight={null}
        robotError={null}
      />,
    );

    expect(screen.getByText(/Requested joint is enabled/)).toBeVisible();
    expect(screen.getByText(/Target matches the enabled joint set/)).toBeVisible();
    expect(consoleError).not.toHaveBeenCalled();
  });
});
