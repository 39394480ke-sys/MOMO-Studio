import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  cancelCalibrationSession,
  completeCalibrationSession,
  confirmCalibrationJoint,
  previewCalibrationJoint,
  readCalibrationJoint,
  startCalibrationSession,
} from '../../api/client';
import type { CalibrationJointPreview, CalibrationWorkflowStatus } from '../../api/types';
import { CalibrationWizard } from './CalibrationWizard';

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  cancelCalibrationSession: vi.fn(),
  completeCalibrationSession: vi.fn(),
  confirmCalibrationJoint: vi.fn(),
  previewCalibrationJoint: vi.fn(),
  readCalibrationJoint: vi.fn(),
  startCalibrationSession: vi.fn(),
}));

const session: CalibrationWorkflowStatus = {
  session_id: 'calibration-session',
  authorization_session_id: 'operator-session',
  robot_id: 'primary',
  variant: 'V2',
  profile_fingerprint: 'b'.repeat(64),
  base_revision: null,
  base_calibration_fingerprint: null,
  source: 'EXISTING_REAL',
  draft: {
    robot_variant: 'V2',
    profile_fingerprint: 'b'.repeat(64),
    enabled_joints: ['j1'],
    created_at: '2026-08-24T03:00:00Z',
    base_revision: null,
    base_calibration_fingerprint: null,
    joints: [{
      joint_id: 'j1',
      servo_id: 1,
      present_raw: null,
      logical_value: null,
      direction: null,
      phase: null,
      raw_bounds: null,
      operating_mode: null,
    }],
  },
  state: 'ACTIVE',
  required_joint_ids: ['j1'],
  confirmed_joint_ids: [],
  selected_joint_id: null,
  observed_raw: null,
  preview: null,
  save_preview: null,
  saved_revision: null,
  saved_calibration_fingerprint: null,
  updated_at: '2026-08-24T03:00:00Z',
};

const preview: CalibrationJointPreview = {
  session_id: session.session_id,
  joint_id: 'j1',
  servo_id: 1,
  observed_raw: 2048,
  logical_value: 10,
  unit: 'deg',
  operating_mode: 'MULTI_TURN',
  direction: 1,
  home_present_raw: 1934,
  phase: 0,
  raw_bounds: [0, 4095],
  round_trip_logical_value: 10,
  mapping_error: 0,
  preview_fingerprint: 'c'.repeat(64),
};

beforeEach(() => {
  vi.mocked(cancelCalibrationSession).mockReset();
  vi.mocked(completeCalibrationSession).mockReset();
  vi.mocked(confirmCalibrationJoint).mockReset();
  vi.mocked(previewCalibrationJoint).mockReset();
  vi.mocked(readCalibrationJoint).mockReset();
  vi.mocked(startCalibrationSession).mockReset();
});

describe('protected current-angle Calibration Wizard', () => {
  it('performs no request until an explicitly connected operator starts it', () => {
    const { rerender } = render(
      <CalibrationWizard connected={false} initiallyConfigured={false} />,
    );

    expect(screen.getByText('Not configured')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start initial calibration' })).toBeDisabled();
    expect(startCalibrationSession).not.toHaveBeenCalled();
    expect(readCalibrationJoint).not.toHaveBeenCalled();

    rerender(<CalibrationWizard connected initiallyConfigured={false} />);
    expect(screen.getByRole('button', { name: 'Start initial calibration' })).toBeEnabled();
    expect(startCalibrationSession).not.toHaveBeenCalled();
  });

  it('reads only the selected joint, previews every mapping field, confirms, and saves', async () => {
    vi.mocked(startCalibrationSession).mockResolvedValue(session);
    vi.mocked(readCalibrationJoint).mockResolvedValue({
      ...session,
      selected_joint_id: 'j1',
      observed_raw: 2048,
    });
    vi.mocked(previewCalibrationJoint).mockResolvedValue(preview);
    vi.mocked(confirmCalibrationJoint).mockResolvedValue({
      ...session,
      state: 'READY_TO_SAVE',
      confirmed_joint_ids: ['j1'],
      selected_joint_id: 'j1',
      observed_raw: 2048,
      save_preview: {
        session_id: session.session_id,
        base_revision: session.base_revision,
        base_calibration_fingerprint: null,
        source: 'EXISTING_REAL',
        proposed_calibration_fingerprint: 'd'.repeat(64),
        joints: [{
          joint_id: 'j1',
          servo_id: 1,
          operating_mode: 'MULTI_TURN',
          direction: 1,
          home_present_raw: 1934,
          phase: 0,
          raw_bounds: [0, 4095],
        }],
      },
    });
    vi.mocked(completeCalibrationSession).mockResolvedValue({
      revision: 1,
      calibration_fingerprint: 'd'.repeat(64),
      previous_calibration_fingerprint: null,
      variant: 'V2',
      created_at: '2026-08-24T03:01:00Z',
    });

    render(<CalibrationWizard connected initiallyConfigured={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start initial calibration' }));
    expect(await screen.findByText(/Draft · Initial calibration → Revision 1/)).toBeVisible();
    expect(await screen.findByRole('button', { name: 'Read selected joint' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Read selected joint' }));
    await waitFor(() => expect(readCalibrationJoint).toHaveBeenCalledWith(
      'calibration-session',
      'j1',
    ));
    expect(await screen.findByText('2048')).toBeVisible();

    fireEvent.change(screen.getByLabelText('Current logical value'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Multi-turn phase (when required)'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Raw lower bound'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Raw upper bound'), { target: { value: '4095' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview mapping' }));

    expect(await screen.findByText('Selected-joint mapping preview')).toBeVisible();
    expect(previewCalibrationJoint).toHaveBeenCalledWith(
      'calibration-session',
      {
        joint_id: 'j1',
        logical_value: 10,
        direction: 1,
        phase: 0,
        raw_bounds: [0, 4095],
      },
    );

    const confirmButton = screen.getByRole('button', { name: 'Confirm this joint only' });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Type the exact joint confirmation'), {
      target: { value: 'CONFIRM CALIBRATION JOINT' },
    });
    fireEvent.click(confirmButton);
    expect(await screen.findByText('Complete calibration preview')).toBeVisible();
    expect(screen.getByRole('table', { name: 'Complete proposed calibration mapping' })).toBeVisible();
    expect(confirmCalibrationJoint).toHaveBeenCalledWith(
      'calibration-session',
      'j1',
      preview.preview_fingerprint,
      'CONFIRM CALIBRATION JOINT',
    );

    const saveButton = screen.getByRole('button', { name: 'Save new calibration revision' });
    expect(saveButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Type the exact save confirmation'), {
      target: { value: 'SAVE CALIBRATION' },
    });
    fireEvent.click(saveButton);

    expect(await screen.findByText('Calibration revision saved')).toBeVisible();
    expect(screen.getByText(/Calibration configured · Field acceptance pending · Real motion blocked/)).toBeVisible();
    expect(completeCalibrationSession).toHaveBeenCalledWith(
      'calibration-session',
      'd'.repeat(64),
      'SAVE CALIBRATION',
    );
  });
});
