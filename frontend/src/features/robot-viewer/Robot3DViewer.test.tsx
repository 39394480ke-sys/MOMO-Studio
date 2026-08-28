import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const runtimeMocks = vi.hoisted(() => ({
  create: vi.fn(),
  dispose: vi.fn(),
  setJointValues: vi.fn(),
  options: null as null | {
    variant: 'V1' | 'V2';
    initialJointValues: Readonly<Record<string, number>>;
    onReady: () => void;
    onError: (error: { code: string }) => void;
  },
}));

vi.mock('./viewerRuntime', () => ({
  createRobotViewerRuntime: runtimeMocks.create,
}));

import { Robot3DViewer } from './Robot3DViewer';
import componentSource from './Robot3DViewer.tsx?raw';
import transformSource from './jointTransforms.ts?raw';
import runtimeSource from './viewerRuntime.ts?raw';
import assetSource from './viewerAssets.ts?raw';

const definitions = [
  { joint_id: 'j10', joint_type: 'PRISMATIC' as const, domain_unit: 'mm' as const, minimum: 0, maximum: 500 },
  { joint_id: 'j11', joint_type: 'REVOLUTE' as const, domain_unit: 'deg' as const, minimum: -180, maximum: 180 },
];

describe('Robot3DViewer', () => {
  beforeEach(() => {
    vi.stubGlobal('WebGLRenderingContext', class WebGLRenderingContext {});
    runtimeMocks.dispose.mockReset();
    runtimeMocks.setJointValues.mockReset();
    runtimeMocks.create.mockReset().mockImplementation((options) => {
      runtimeMocks.options = options;
      return {
        dispose: runtimeMocks.dispose,
        setJointValues: runtimeMocks.setJointValues,
      };
    });
    runtimeMocks.options = null;
  });

  it('loads the authored V1 model and maps only its enabled Profile joints', async () => {
    render(
      <Robot3DViewer
        enabledJointIds={['j11']}
        jointDefinitions={definitions.slice(1)}
        jointPositions={{ j10: 400, j11: 90 }}
        jointUnits={{ j11: 'deg' }}
        variant="V1"
      />,
    );

    await waitFor(() => expect(runtimeMocks.create).toHaveBeenCalledTimes(1));
    expect(runtimeMocks.options?.variant).toBe('V1');
    expect(runtimeMocks.options?.initialJointValues).toEqual({
      j11: Math.PI / 2,
    });
    expect(runtimeMocks.options?.initialJointValues).not.toHaveProperty('j10');

    act(() => runtimeMocks.options?.onReady());
    expect(screen.getByText(/V1 三维模型已加载/)).toBeVisible();
  });

  it('updates only the read-only runtime and disposes it on unmount', async () => {
    const { rerender, unmount } = render(
      <Robot3DViewer
        enabledJointIds={['j10', 'j11']}
        jointDefinitions={definitions}
        jointPositions={{ j10: 100, j11: 90 }}
        jointUnits={{ j10: 'mm', j11: 'deg' }}
        variant="V2"
      />,
    );

    await waitFor(() => expect(runtimeMocks.create).toHaveBeenCalledTimes(1));
    expect(runtimeMocks.options?.variant).toBe('V2');
    expect(runtimeMocks.options?.initialJointValues).toEqual({
      j10: 0.1,
      j11: Math.PI / 2,
    });

    act(() => runtimeMocks.options?.onReady());
    expect(screen.getByText(/V2 三维模型已加载/)).toBeVisible();

    rerender(
      <Robot3DViewer
        enabledJointIds={['j10', 'j11']}
        jointDefinitions={definitions}
        jointPositions={{ j10: 600, j11: -90 }}
        jointUnits={{ j10: 'mm', j11: 'deg' }}
        variant="V2"
      />,
    );
    expect(runtimeMocks.create).toHaveBeenCalledTimes(1);
    expect(runtimeMocks.setJointValues).toHaveBeenLastCalledWith({
      j10: 0.5,
      j11: -Math.PI / 2,
    });

    unmount();
    expect(runtimeMocks.dispose).toHaveBeenCalledTimes(1);
  });

  it('disposes and recreates the runtime when the robot variant changes', async () => {
    const { rerender, unmount } = render(
      <Robot3DViewer
        enabledJointIds={['j11']}
        jointDefinitions={definitions.slice(1)}
        jointPositions={{ j11: 0 }}
        jointUnits={{ j11: 'deg' }}
        variant="V1"
      />,
    );

    await waitFor(() => expect(runtimeMocks.create).toHaveBeenCalledTimes(1));
    expect(runtimeMocks.options?.variant).toBe('V1');
    const firstRuntimeOptions = runtimeMocks.options;

    rerender(
      <Robot3DViewer
        enabledJointIds={['j10', 'j11']}
        jointDefinitions={definitions}
        jointPositions={{ j10: 0, j11: 0 }}
        jointUnits={{ j10: 'mm', j11: 'deg' }}
        variant="V2"
      />,
    );

    await waitFor(() => expect(runtimeMocks.create).toHaveBeenCalledTimes(2));
    expect(runtimeMocks.dispose).toHaveBeenCalledTimes(1);
    expect(runtimeMocks.options?.variant).toBe('V2');

    act(() => firstRuntimeOptions?.onReady());
    expect(screen.queryByText(/V1 三维模型已加载/)).not.toBeInTheDocument();
    act(() => runtimeMocks.options?.onReady());
    expect(screen.getByText(/V2 三维模型已加载/)).toBeVisible();

    unmount();
    expect(runtimeMocks.dispose).toHaveBeenCalledTimes(2);
  });

  it('shows an explicit asset-failure fallback', async () => {
    render(
      <Robot3DViewer
        enabledJointIds={['j10', 'j11']}
        jointDefinitions={definitions}
        jointPositions={{ j10: 0, j11: 0 }}
        jointUnits={{ j10: 'mm', j11: 'deg' }}
        variant="V2"
      />,
    );

    await waitFor(() => expect(runtimeMocks.options).not.toBeNull());
    act(() => runtimeMocks.options?.onError({ code: 'ASSET_LOAD_FAILED' }));
    expect(screen.getByRole('alert')).toHaveTextContent(/URDF 或 STL 资产加载失败/);
  });

  it('fails closed before loading when an enabled joint has no explicit valid unit', () => {
    render(
      <Robot3DViewer
        enabledJointIds={['j10', 'j11']}
        jointDefinitions={definitions}
        jointPositions={{ j10: 0, j11: 0 }}
        jointUnits={{ j10: 'mm' }}
        variant="V2"
      />,
    );

    expect(runtimeMocks.create).not.toHaveBeenCalled();
    expect(screen.getAllByText(/状态单位与 Profile 不一致/)).toHaveLength(2);
  });

  it('has no API client, backend request or hardware-control dependency', () => {
    const productionSources = [componentSource, transformSource, runtimeSource, assetSource];
    for (const source of productionSources) {
      expect(source).not.toMatch(/(?:from\s+|import\()['"][^'"]*(?:\/api\/|api\/client)/);
      expect(source).not.toMatch(/\b(?:fetch|XMLHttpRequest)\s*\(/);
      expect(source).not.toMatch(/\b(?:connect|home|calibrate|moveRobot)\s*\(/);
    }
  });
});
