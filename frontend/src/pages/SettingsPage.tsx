import { Check, CircleAlert, Minus, ShieldCheck, X } from 'lucide-react';

import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';

function MatchValue({ value }: { value: boolean | null | undefined }) {
  if (value === true) {
    return (
      <span className="match-value match-value--yes">
        <Check aria-hidden="true" /> Yes
      </span>
    );
  }
  if (value === false) {
    return (
      <span className="match-value match-value--no">
        <X aria-hidden="true" /> No
      </span>
    );
  }
  return (
    <span className="match-value match-value--unknown">
      <Minus aria-hidden="true" /> Not configured
    </span>
  );
}

export function SettingsPage() {
  const {
    backend,
    stale,
    robot,
    profile,
    calibration,
    diagnostics,
    error,
    pendingAction,
    switchVariant,
  } = useRuntimeStatus();
  const switchingDisabled =
    backend !== 'connected' || robot?.connected === true || pendingAction !== null;
  const activeVariant = robot?.variant ?? profile?.profile.variant ?? 'V2';

  return (
    <div className="page">
      <PageIntro
        title="Settings"
        description="Robot identity, profile provenance, calibration compatibility, and policy."
        detail="Variant changes are available only while the Active Robot is disconnected."
      />

      {(backend === 'unavailable' || error) && (
        <div className="settings-notice" role="status">
          <CircleAlert aria-hidden="true" />
          <span>
            {stale ? 'Backend unavailable · settings are stale' : error || 'Backend unavailable'}
          </span>
        </div>
      )}

      <section className="settings-section" aria-labelledby="robot-settings-title">
        <div className="settings-section__heading">
          <p className="section-kicker">Robot</p>
          <h2 id="robot-settings-title">Active Variant</h2>
        </div>
        <fieldset className="variant-selector" disabled={switchingDisabled}>
          <legend>Robot variant</legend>
          {(['V1', 'V2'] as const).map((variant) => (
            <button
              aria-pressed={activeVariant === variant}
              className={activeVariant === variant ? 'variant-selector__active' : ''}
              key={variant}
              onClick={() => void switchVariant(variant)}
              type="button"
            >
              {variant}
            </button>
          ))}
        </fieldset>
        <p className="variant-summary">
          {activeVariant === 'V1'
            ? 'V1 · Five revolute joints · No linear rail'
            : 'V2 · Linear rail plus five revolute joints'}
        </p>
        <dl className="settings-list">
          <div>
            <dt>Enabled joints</dt>
            <dd>{profile?.profile.enabled_joints.join(', ').toUpperCase() ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Fingerprint</dt>
            <dd>
              <code>{profile?.fingerprint ?? 'Pending'}</code>
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{profile?.profile.source ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Source revision</dt>
            <dd>
              <code>{profile?.profile.source_revision ?? 'Pending'}</code>
            </dd>
          </div>
          <div>
            <dt>Verification</dt>
            <dd>{profile?.profile.verification_status ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Template</dt>
            <dd>{profile ? (profile.profile.template ? 'Yes' : 'No') : 'Pending'}</dd>
          </div>
        </dl>
      </section>

      <section className="settings-section" aria-labelledby="calibration-settings-title">
        <div className="settings-section__heading settings-section__heading--inline">
          <div>
            <p className="section-kicker">Calibration</p>
            <h2 id="calibration-settings-title">Compatibility</h2>
          </div>
          <strong className="settings-status">{calibration?.status ?? 'PENDING'}</strong>
        </div>
        <dl className="compatibility-grid">
          <div>
            <dt>Configured</dt>
            <dd><MatchValue value={calibration?.configured} /></dd>
          </div>
          <div>
            <dt>Template</dt>
            <dd><MatchValue value={calibration?.template} /></dd>
          </div>
          <div>
            <dt>Variant match</dt>
            <dd><MatchValue value={calibration?.variant_match} /></dd>
          </div>
          <div>
            <dt>Profile match</dt>
            <dd><MatchValue value={calibration?.profile_match} /></dd>
          </div>
          <div>
            <dt>Joint set match</dt>
            <dd><MatchValue value={calibration?.joint_set_match} /></dd>
          </div>
          <div>
            <dt>Hardware mapping</dt>
            <dd><MatchValue value={calibration?.mapping_match} /></dd>
          </div>
          <div>
            <dt>Complete</dt>
            <dd><MatchValue value={calibration?.complete} /></dd>
          </div>
        </dl>
        <div className="readiness-block">
          <ShieldCheck aria-hidden="true" />
          <div>
            <strong>Real readiness: {calibration?.real_readiness ?? 'PENDING'}</strong>
            <ul>
              {(calibration?.blocking_reasons ?? ['Waiting for backend diagnostics']).map(
                (reason) => <li key={reason}>{reason}</li>,
              )}
            </ul>
          </div>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="diagnostics-settings-title">
        <div className="settings-section__heading">
          <p className="section-kicker">Diagnostics</p>
          <h2 id="diagnostics-settings-title">Stage Policy</h2>
        </div>
        <dl className="settings-list">
          <div>
            <dt>Hardware access</dt>
            <dd>{diagnostics?.hardware_access_policy ?? 'DISABLED'}</dd>
          </div>
          <div>
            <dt>Runtime state</dt>
            <dd><code>{diagnostics?.runtime_state_path ?? 'data/runtime/robots/primary.json'}</code></dd>
          </div>
          <div>
            <dt>Runtime valid</dt>
            <dd>{diagnostics ? (diagnostics.runtime_state_valid ? 'Yes' : 'No') : 'Pending'}</dd>
          </div>
          <div>
            <dt>Runtime diagnostic</dt>
            <dd>{diagnostics?.runtime_state_diagnostic ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Backend version</dt>
            <dd>{diagnostics?.backend_version ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Legacy source</dt>
            <dd><code>{diagnostics?.legacy_source_commit ?? 'Pending'}</code></dd>
          </div>
          <div>
            <dt>Policy</dt>
            <dd>{diagnostics?.stage_policy ?? 'STAGE_2_DRY_RUN_ONLY'}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
