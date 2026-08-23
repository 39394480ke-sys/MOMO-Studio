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
}

const parameterFields: Array<{
  key: keyof ControlParameters;
  label: string;
  min: number;
  max: number;
  step: number;
  unit: string;
}> = [
  { key: 'jointStepDeg', label: 'Joint step', min: 0.1, max: 15, step: 0.1, unit: 'deg' },
  { key: 'railStepMm', label: 'Rail step', min: 0.1, max: 25, step: 0.1, unit: 'mm' },
  { key: 'continuousSpeedDegS', label: 'Joint hold speed', min: 0.1, max: 45, step: 0.1, unit: 'deg/s' },
  { key: 'railSpeedMmS', label: 'Rail hold speed', min: 0.1, max: 50, step: 0.1, unit: 'mm/s' },
  { key: 'cartesianStepMm', label: 'Cartesian step', min: 0.1, max: 25, step: 0.1, unit: 'mm' },
  { key: 'rotationStepDeg', label: 'Rotation step', min: 0.1, max: 10, step: 0.1, unit: 'deg' },
  { key: 'durationS', label: 'Move duration', min: 0.1, max: 60, step: 0.1, unit: 's' },
  { key: 'speedScale', label: 'Speed scale', min: 0.05, max: 1, step: 0.05, unit: '×' },
];

export function MotionParametersPanel({
  parameters,
  availability,
  pending,
  motionLocked,
  onChange,
  onHome,
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
          <p className="section-kicker">Motion Parameters</p>
          <h2 id="motion-parameters-title">Safe defaults</h2>
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
      <button
        className="command-button command-button--home"
        disabled={disabled}
        onClick={() => setConfirmingHome(true)}
        type="button"
      >
        <Home aria-hidden="true" /> {pending === 'home' ? 'Submitting…' : 'Home robot'}
      </button>
      {confirmingHome ? (
        <div aria-label="Confirm Home" className="home-confirmation" role="alertdialog">
          <strong>Home every enabled joint?</strong>
          <p>This remains a safety-gated Dry Run command.</p>
          <div>
            <button onClick={() => setConfirmingHome(false)} type="button">Cancel Home</button>
            <button
              className="command-button"
              onClick={() => {
                setConfirmingHome(false);
                void onHome();
              }}
              type="button"
            >
              Confirm Home
            </button>
          </div>
        </div>
      ) : null}
      <p className="control-hint">Home requires an explicit confirmation and still passes through Dry Run preflight.</p>
    </section>
  );
}
