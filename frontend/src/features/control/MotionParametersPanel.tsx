import { Home } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { ControlParameters, MotionAvailability } from './controlTypes';

interface MotionParametersPanelProps {
  parameters: ControlParameters;
  availability: MotionAvailability;
  pending: string | null;
  motionLocked: boolean;
  onChange: <Key extends keyof ControlParameters>(key: Key, value: ControlParameters[Key]) => void;
  onHome: () => Promise<void>;
  showHome?: boolean;
}

const parameterFields: Array<{
  key: keyof ControlParameters;
  label: string;
  min: number;
  max: number;
  step: number;
  unit: string;
}> = [
  { key: 'jointStepDeg', label: '关节单步', min: 0.1, max: 15, step: 0.1, unit: 'deg' },
  { key: 'railStepMm', label: '导轨单步', min: 0.1, max: 25, step: 0.1, unit: 'mm' },
  { key: 'continuousSpeedDegS', label: '关节按住速度', min: 0.1, max: 45, step: 0.1, unit: 'deg/s' },
  { key: 'railSpeedMmS', label: '导轨按住速度', min: 0.1, max: 50, step: 0.1, unit: 'mm/s' },
  { key: 'cartesianStepMm', label: '笛卡尔单步', min: 0.1, max: 25, step: 0.1, unit: 'mm' },
  { key: 'rotationStepDeg', label: '旋转单步', min: 0.1, max: 10, step: 0.1, unit: 'deg' },
  { key: 'durationS', label: '运动时长', min: 0.1, max: 60, step: 0.1, unit: 's' },
  { key: 'speedScale', label: '速度倍率', min: 0.05, max: 1, step: 0.05, unit: '×' },
];

export function MotionParametersPanel({
  parameters,
  availability,
  pending,
  motionLocked,
  onChange,
  onHome,
  showHome = true,
}: MotionParametersPanelProps) {
  const disabled = !availability.allowed || pending !== null || motionLocked;
  const [confirmingHome, setConfirmingHome] = useState(false);

  useEffect(() => {
    if (disabled) setConfirmingHome(false);
  }, [disabled]);

  return (
    <section className="control-panel control-panel--parameters" aria-labelledby="motion-parameters-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="section-kicker">运动参数</p>
          <h2 id="motion-parameters-title">安全默认值</h2>
        </div>
      </div>
      <div className="parameter-grid">
        {parameterFields.map((field) => (
          <label key={field.key}>
            <span>{field.label}</span>
            <span className="number-with-unit">
              <input
                aria-label={`${field.label} (${field.unit})`}
                disabled={disabled}
                max={field.max}
                min={field.min}
                onChange={(event) => onChange(field.key, event.currentTarget.valueAsNumber)}
                step={field.step}
                type="number"
                value={parameters[field.key]}
              />
              <span>{field.unit}</span>
            </span>
          </label>
        ))}
      </div>
      {showHome ? <button
        className="command-button command-button--home"
        disabled={disabled}
        onClick={() => setConfirmingHome(true)}
        type="button"
      >
        <Home aria-hidden="true" /> {pending === 'home' ? '提交中…' : '机器人回零'}
      </button> : null}
      {showHome && confirmingHome ? (
        <div aria-label="确认回零" className="home-confirmation" role="alertdialog">
          <strong>让所有已启用关节回零？</strong>
          <p>此操作仍受仿真运行安全门控保护。</p>
          <div>
            <button onClick={() => setConfirmingHome(false)} type="button">取消回零</button>
            <button
              className="command-button"
              onClick={() => {
                setConfirmingHome(false);
                void onHome();
              }}
              type="button"
            >
              确认回零
            </button>
          </div>
        </div>
      ) : null}
      {showHome ? <p className="control-hint">回零需要明确确认，并且仍须通过仿真运行预检。</p> : null}
    </section>
  );
}
