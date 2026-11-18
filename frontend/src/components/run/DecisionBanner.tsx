// The top of a finished run: the decision, why, who owns the next step, and what passed.

import { ArrowRight, Check, ChevronDown, Minus } from 'lucide-react'
import { useState } from 'react'

import { DecisionBadge, Eyebrow } from '@/components/common'
import type { Decision, RunDetail } from '@/lib/api'
import { moment } from '@/lib/format'
import { cn } from '@/lib/utils'

import { ToneMark } from './Checklist'
import { toneOf, TONES } from './findings'
import { ReviewPanel } from './ReviewPanel'

const LOOK: Record<Decision, { frame: string; rule: string }> = {
  APPROVE: { frame: 'border-approve-line bg-approve-soft', rule: 'border-approve-line' },
  REVIEW: { frame: 'border-review-line bg-review-soft', rule: 'border-review-line' },
  REJECT: { frame: 'border-reject-line bg-reject-soft', rule: 'border-reject-line' },
}

export function DecisionBanner({ run, onResolved }: { run: RunDetail; onResolved: (run: RunDetail) => void }) {
  const detail = run.decision_detail
  const [showPassed, setShowPassed] = useState(false)
  if (!detail) return null
  const look = LOOK[detail.decision]
  // "Needs review: the invoice takes…" -> the part after the colon, as the sentence to read.
  const [lead, ...rest] = detail.headline.split(': ')
  const body = rest.join(': ')

  return (
    <section className={cn('overflow-hidden rounded-lg border', look.frame)}>
      <div className="grid grid-cols-[1fr_380px]">
        {/* Left: the decision and the reasons. */}
        <div className="px-5 py-4">
          <div className="flex items-center gap-2.5">
            <DecisionBadge decision={detail.decision} large />
            <span className="text-xs text-muted-foreground">
              Decided by code from {detail.reasons.length + detail.passed.length + detail.not_checked.length} check results
            </span>
          </div>
          <h2 className="mt-2.5 max-w-3xl text-[21px] leading-snug font-semibold tracking-tight">
            {body ? (
              <>
                {lead}: <span className="font-medium">{body}</span>
              </>
            ) : (
              lead
            )}
          </h2>

          {detail.reasons.length > 0 && (
            <ul className="mt-3.5 max-w-3xl space-y-2.5">
              {detail.reasons.map((reason) => {
                const tone = toneOf(reason)
                return (
                  <li key={reason.code} className="flex gap-2.5">
                    <ToneMark tone={tone} className="mt-0.5 bg-card" />
                    <div>
                      <p className="leading-relaxed">{reason.text}</p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        <span className={cn('font-semibold', TONES[tone].text)}>{TONES[tone].label}</span>
                        <span className="code ml-2">{reason.code}</span>
                      </p>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}

          <button
            type="button"
            onClick={() => setShowPassed(!showPassed)}
            aria-expanded={showPassed}
            className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground/80 hover:text-foreground"
          >
            <Check className="size-3.5 text-approve" strokeWidth={3} />
            {detail.passed.length} checks passed
            {detail.not_checked.length > 0 && <>, {detail.not_checked.length} could not be run</>}
            <ChevronDown className={cn('size-3.5 transition-transform', showPassed && 'rotate-180')} />
          </button>

          {showPassed && (
            <div className={cn('mt-2.5 border-t pt-3', look.rule)}>
              <ul className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
                {detail.passed.map((text) => (
                  <li key={text} className="flex gap-2">
                    <Check className="mt-0.5 size-3.5 shrink-0 text-approve" strokeWidth={3} />
                    <span className="text-foreground/80">{text}</span>
                  </li>
                ))}
                {detail.not_checked.map((text) => (
                  <li key={text} className="flex gap-2">
                    <Minus className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    <span className="text-muted-foreground">Not checked: {text.replace(/^[A-Z_]+: /, '')}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right: who acts next, and (for a review) the reviewer's controls. */}
        <div className={cn('border-l bg-card/70 px-5 py-4', look.rule)}>
          <Eyebrow>{run.resolution ? 'Next step when decided' : 'Next step'}</Eyebrow>
          <p className="mt-1.5 flex items-center gap-1.5 font-semibold">
            <ArrowRight className="size-3.5" />
            {detail.owner === 'none' ? 'No one needs to act' : detail.owner_label}
          </p>
          <p className="mt-1 leading-relaxed text-foreground/85">{detail.next_action}</p>

          {run.resolution && (
            <div className="mt-4 rounded-md border bg-card px-3 py-2.5">
              <Eyebrow className={run.resolution.action === 'approved' ? 'text-approve' : 'text-reject'}>
                {run.resolution.action === 'approved' ? 'Approved by a reviewer' : 'Rejected by a reviewer'}
              </Eyebrow>
              <p className="mt-1">“{run.resolution.comment}”</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {moment(run.resolution.resolved_at)}
                {run.resolution.action === 'approved' && run.po_id && <> · booked against <span className="num">{run.po_id}</span></>}
              </p>
            </div>
          )}

          {run.state === 'awaiting_review' && <ReviewPanel run={run} onResolved={onResolved} />}
        </div>
      </div>
    </section>
  )
}
