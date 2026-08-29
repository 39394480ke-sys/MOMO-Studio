import { useEffect, useMemo, useRef, useState } from 'react';

import {
  buildUrdfJointValues,
  type RobotViewerJointDefinition,
  type RobotViewerJointPositions,
  type RobotViewerJointUnits,
} from './jointTransforms';
import type { RobotViewerRuntime } from './viewerRuntime';
import './Robot3DViewer.css';

export interface Robot3DViewerProps {
  readonly variant: 'V1' | 'V2';
  readonly jointDefinitions: readonly RobotViewerJointDefinition[];
  readonly enabledJointIds: readonly string[];
  readonly jointPositions: RobotViewerJointPositions;
  readonly jointUnits: RobotViewerJointUnits;
  readonly className?: string;
  readonly ariaLabel?: string;
  readonly badgeLabel?: string;
  readonly safetyNote?: string;
}

type ViewerState =
  | { readonly kind: 'loading'; readonly message: string }
  | { readonly kind: 'ready'; readonly message: string }
  | { readonly kind: 'unavailable'; readonly message: string }
  | { readonly kind: 'error'; readonly message: string };

interface VariantRuntimeState {
  readonly variant: Robot3DViewerProps['variant'];
  readonly state: ViewerState;
}

function unavailableState(
  variant: Robot3DViewerProps['variant'],
  enabledJointIds: readonly string[],
  jointDefinitions: readonly RobotViewerJointDefinition[],
  jointPositions: RobotViewerJointPositions,
  jointUnits: RobotViewerJointUnits,
): ViewerState | null {
  if (enabledJointIds.length === 0) {
    return {
      kind: 'unavailable',
      message: `当前 ${variant} 配置没有明确的 enabled_joints，三维视图未加载。`,
    };
  }

  const definitionsById = new Map(
    jointDefinitions.map((definition) => [definition.joint_id, definition]),
  );
  if (enabledJointIds.some((jointId) => !definitionsById.has(jointId))) {
    return {
      kind: 'unavailable',
      message: '启用关节缺少对应的 Profile 定义，三维视图未加载。',
    };
  }
  for (const jointId of new Set(enabledJointIds)) {
    const definition = definitionsById.get(jointId);
    const position = jointPositions[jointId];
    if (
      definition === undefined ||
      !Number.isFinite(definition.minimum) ||
      !Number.isFinite(definition.maximum) ||
      definition.minimum > definition.maximum ||
      !Number.isFinite(position)
    ) {
      return {
        kind: 'unavailable',
        message: '启用关节缺少有效的 Profile 限制或状态值，三维视图未加载。',
      };
    }
    if (jointUnits[jointId] !== definition.domain_unit) {
      return {
        kind: 'unavailable',
        message: '启用关节状态单位与 Profile 不一致，三维视图未加载。',
      };
    }
  }
  return null;
}

function loadingState(variant: Robot3DViewerProps['variant']): ViewerState {
  return {
    kind: 'loading',
    message: `正在加载 ${variant} URDF 与 STL 资产…`,
  };
}

function runtimeFailureMessage(
  code: string,
  variant: Robot3DViewerProps['variant'],
): string {
  if (code === 'WEBGL_UNAVAILABLE') {
    return '此设备无法初始化 WebGL；已切换为只读文字状态。';
  }
  if (code === 'RESIZE_OBSERVER_UNAVAILABLE') {
    return '此浏览器缺少安全调整画布尺寸所需的能力；三维视图不可用。';
  }
  if (code === 'INVALID_MODEL') {
    return `${variant} 模型没有可显示的有效几何体；三维视图不可用。`;
  }
  if (code === 'JOINT_MAPPING_MISMATCH') {
    return `${variant} 模型与当前 Profile 的关节映射不完整；三维视图已停止更新。`;
  }
  return `${variant} URDF 或 STL 资产加载失败；未显示不完整模型。`;
}

export function Robot3DViewer({
  variant,
  jointDefinitions,
  enabledJointIds,
  jointPositions,
  jointUnits,
  className,
  ariaLabel = 'MOMO 机械臂只读三维视图',
  badgeLabel = '3D · SIMULATION ONLY',
  safetyNote = '仅用于可视化 · 不连接或控制实体机械臂',
}: Robot3DViewerProps) {
  const unavailable = unavailableState(
    variant,
    enabledJointIds,
    jointDefinitions,
    jointPositions,
    jointUnits,
  );
  const unavailableKind = unavailable?.kind;
  const [runtimeState, setRuntimeState] = useState<VariantRuntimeState>(() => ({
    variant,
    state: loadingState(variant),
  }));
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const runtimeRef = useRef<RobotViewerRuntime | null>(null);

  const urdfJointValues = useMemo(
    () => buildUrdfJointValues({
      jointDefinitions,
      enabledJointIds,
      jointPositions,
      jointUnits,
    }),
    [enabledJointIds, jointDefinitions, jointPositions, jointUnits],
  );
  const latestJointValuesRef = useRef(urdfJointValues);
  latestJointValuesRef.current = urdfJointValues;

  useEffect(() => {
    if (unavailableKind !== undefined) return undefined;
    if (
      typeof globalThis.WebGLRenderingContext === 'undefined' &&
      typeof globalThis.WebGL2RenderingContext === 'undefined'
    ) {
      setRuntimeState({
        variant,
        state: {
          kind: 'error',
          message: runtimeFailureMessage('WEBGL_UNAVAILABLE', variant),
        },
      });
      return undefined;
    }
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (host === null || canvas === null) return undefined;

    let cancelled = false;
    setRuntimeState({ variant, state: loadingState(variant) });

    void import('./viewerRuntime')
      .then(({ createRobotViewerRuntime }) => {
        if (cancelled) return;
        const runtime = createRobotViewerRuntime({
          host,
          canvas,
          variant,
          initialJointValues: latestJointValuesRef.current,
          onReady: () => {
            if (!cancelled) {
              setRuntimeState({
                variant,
                state: {
                  kind: 'ready',
                  message: `${variant} 三维模型已加载；显示值已按 Profile 限制。`,
                },
              });
            }
          },
          onError: (error) => {
            if (!cancelled) {
              setRuntimeState({
                variant,
                state: {
                  kind: 'error',
                  message: runtimeFailureMessage(error.code, variant),
                },
              });
            }
          },
        });
        if (cancelled) {
          runtime.dispose();
          return;
        }
        runtimeRef.current = runtime;
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const code = typeof error === 'object' && error !== null && 'code' in error
          ? String(error.code)
          : 'ASSET_LOAD_FAILED';
        setRuntimeState({
          variant,
          state: { kind: 'error', message: runtimeFailureMessage(code, variant) },
        });
      });

    return () => {
      cancelled = true;
      const runtime = runtimeRef.current;
      runtimeRef.current = null;
      runtime?.dispose();
    };
  }, [unavailableKind, variant]);

  useEffect(() => {
    runtimeRef.current?.setJointValues(urdfJointValues);
  }, [urdfJointValues]);

  const state = unavailable ?? (
    runtimeState.variant === variant ? runtimeState.state : loadingState(variant)
  );
  const rootClassName = ['robot-3d-viewer', className].filter(Boolean).join(' ');

  return (
    <section
      aria-label={ariaLabel}
      className={rootClassName}
      data-viewer-status={state.kind}
    >
      <div className="robot-3d-viewer__viewport" ref={hostRef}>
        <canvas
          aria-label={`${ariaLabel}画布`}
          className="robot-3d-viewer__canvas"
          ref={canvasRef}
          role="img"
        />
        <span className="robot-3d-viewer__badge">{badgeLabel}</span>
        <span className="robot-3d-viewer__safety-note">{safetyNote}</span>
        {state.kind === 'ready' ? null : (
          <div
            className={`robot-3d-viewer__fallback robot-3d-viewer__fallback--${state.kind}`}
            role={state.kind === 'error' ? 'alert' : 'status'}
          >
            <strong>{state.kind === 'loading' ? '加载三维模型' : '三维视图不可用'}</strong>
            <span>{state.message}</span>
          </div>
        )}
      </div>
      <footer className="robot-3d-viewer__footer">
        <span>{state.message}</span>
        <span>拖动旋转 · 滚轮缩放 · 右键平移</span>
      </footer>
    </section>
  );
}
