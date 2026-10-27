import React from 'react';
import { Check, AlertCircle, Circle, RefreshCw, Minus } from 'lucide-react';

const STANDARD_STAGES = [
  { key: 'queued', label: 'Queued' },
  { key: 'investigating', label: 'Investigate' },
  { key: 'planning', label: 'Plan' },
  { key: 'editing', label: 'Edit' },
  { key: 'testing', label: 'Test' },
  { key: 'repairing', label: 'Repair' },
  { key: 'verifying', label: 'Verify' },
  { key: 'completed', label: 'Finish' },
];

const STAGE_ORDER = {
  queued: 0,
  investigate: 1,
  investigating: 1,
  plan: 2,
  planning: 2,
  edit: 3,
  editing: 3,
  test: 4,
  testing: 4,
  diagnose: 5,
  diagnosing: 5,
  repair: 5,
  repairing: 5,
  verify: 6,
  verifying: 6,
  publishing: 6,
  finish: 7,
  completed: 7,
  needs_human_review: 7,
  failed: 7,
};

/**
 * StageStepper component that accurately highlights progression across
 * autonomous engineering stages, clearly differentiating completed vs skipped steps.
 */
export function StageStepper({ currentStage = 'queued', status = 'queued', events = [] }) {
  const normalizedStage = (currentStage || 'queued').toLowerCase();
  const normalizedStatus = (status || 'queued').toLowerCase();

  const currentIdx = STAGE_ORDER[normalizedStage] ?? 0;
  const isFailed = normalizedStatus === 'failed';
  const isReview = normalizedStatus === 'needs_human_review';
  const isCompleted = normalizedStatus === 'completed';

  // Check if repair was ever triggered in execution events
  const hadRepair = Boolean(
    events &&
    events.some(
      (e) =>
        e.stage === 'repairing' ||
        e.stage === 'diagnosing' ||
        e.event_type === 'repair_started' ||
        e.event_type === 'diagnosis_started'
    )
  );

  return (
    <div className="stage-stepper" aria-label="Task Workflow Progression">
      {STANDARD_STAGES.map((stage, idx) => {
        let stepClass = 'stage-step';
        let icon = <Circle size={12} />;
        let label = stage.label;
        let title = `Stage: ${stage.label}`;

        const isPastThisStep = idx < currentIdx || (idx === 7 && isCompleted);
        const isCurrentStep = idx === currentIdx;

        // Special handling for the conditional 'Repair' stage (idx 5)
        if (stage.key === 'repairing') {
          if (isCurrentStep) {
            stepClass += ' active';
            icon = <RefreshCw size={12} className="spin-animation" />;
            label = 'Repairing...';
            title = 'Stage: Repair — currently attempting corrective fixes';
          } else if (isPastThisStep) {
            if (hadRepair) {
              stepClass += ' completed';
              icon = <Check size={12} />;
              title = 'Stage: Repair — corrective fix applied';
            } else {
              // Bypassed because tests passed on first try
              stepClass += ' skipped';
              icon = <Minus size={12} />;
              label = 'Repair (Skipped)';
              title = 'Stage: Repair — skipped (all unit tests passed on first run)';
            }
          }
        } else if (isPastThisStep) {
          stepClass += ' completed';
          icon = <Check size={12} />;
        } else if (isCurrentStep) {
          if (idx === 7 && isFailed) {
            stepClass += ' badge-failed';
            icon = <AlertCircle size={12} />;
          } else if (idx === 7 && isReview) {
            stepClass += ' badge-review';
            icon = <AlertCircle size={12} />;
          } else {
            stepClass += ' active';
            icon = <RefreshCw size={12} className="spin-animation" />;
            if (stage.key === 'verifying' && normalizedStage === 'publishing') {
              label = 'Publishing...';
              title = 'Stage: Publishing branch and opening PR';
            }
          }
        }

        return (
          <React.Fragment key={stage.key}>
            <div className={stepClass} title={title}>
              {icon}
              <span>{label}</span>
            </div>
            {idx < STANDARD_STAGES.length - 1 && <div className="stage-divider" />}
          </React.Fragment>
        );
      })}
    </div>
  );
}

export default StageStepper;
