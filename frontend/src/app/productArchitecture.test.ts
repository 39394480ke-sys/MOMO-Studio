import { describe, expect, it } from 'vitest';

import clientSource from '../api/client.ts?raw';
import runtimeSource from '../components/RuntimeStatusProvider.tsx?raw';
import controlSource from '../pages/ControlPage.tsx?raw';
import settingsSource from '../pages/SettingsPage.tsx?raw';

describe('product motion architecture', () => {
  it('keeps product lifecycle on the robot routes and out of diagnostics routes', () => {
    const productSource = [clientSource, runtimeSource, controlSource, settingsSource].join('\n');

    expect(productSource).not.toContain("'/device/connect'");
    expect(productSource).not.toContain("'/device/disconnect'");
    expect(productSource).not.toContain('connectRealDevice');
    expect(productSource).not.toContain('disconnectRealDevice');
    expect(runtimeSource).toContain('connectRobot');
    expect(runtimeSource).toContain('disconnectRobot');
    expect(clientSource).toContain("postJson<MotionStopResponse>('/robot/stop')");
  });

  it('does not mount a second commissioning control surface in the product pages', () => {
    expect(controlSource).not.toContain('CommissioningControlAdapter');
    expect(settingsSource).not.toContain('RealHardwarePanel');
  });
});
