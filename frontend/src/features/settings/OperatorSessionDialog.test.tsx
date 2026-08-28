import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DeviceConfirmationEvidence } from '../../api/types';
import { OperatorSessionDialog } from './OperatorSessionDialog';

const rawConfirmation = 'I CONFIRM CURRENT POSE MATCHES URDF ZERO AND RAW TEST CAN MOVE ONE JOINT';

const evidence: DeviceConfirmationEvidence = {
  robot_id: 'primary',
  robot_unit_id: 'MOMO-V2-UNIT-001',
  variant: 'V2',
  profile_fingerprint: 'a'.repeat(64),
  calibration_fingerprint: null,
  kinematics_fingerprint: null,
  masked_serial_port: '/dev/***3871',
  masked_servo_ids: ['**10', '**11', '**12', '**13', '**14', '**15'],
  protocol: 'STS3215',
  session_purpose: 'RAW_DIRECTION_TEST',
  field_acceptance_evidence_id: null,
  physical_estop_required: true,
  workspace_clear_required: true,
  required_confirmation_text: rawConfirmation,
};

describe('Raw direction session confirmation', () => {
  it('uses one field-facing confirmation while preserving the exact backend contract', () => {
    const onConfirm = vi.fn();
    render(
      <OperatorSessionDialog
        error={null}
        evidence={evidence}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
        pending={false}
      />,
    );

    expect(screen.queryByLabelText(/Type the exact confirmation text/)).not.toBeInTheDocument();
    const start = screen.getByRole('button', { name: '开始方向验收' });
    expect(start).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/急停已就位、空间已清空/));
    expect(start).toBeEnabled();
    fireEvent.click(start);

    expect(onConfirm).toHaveBeenCalledWith(rawConfirmation, true, true);
  });
});
