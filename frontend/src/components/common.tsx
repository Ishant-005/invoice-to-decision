// Small building blocks used on every screen.

import { AlertCircle, CheckCircle2, CircleSlash, Eye, Loader2, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import type { Decision, RunState } from '@/lib/api'
import { cn } from '@/lib/utils'

// Colour is never the only signal: every decision has an icon and a word.
const DECISIONS: Record<Decision, { label: string; icon: typeof Eye; classes: string }> = {
  APPROVE: {
    label: 'Approve',
    icon: CheckCircle2,
    classes: 'bg-approve-soft text-approve border-approve-line',
  },
  REVIEW: { label: 'Review', icon: Eye, classes: 'bg-review-soft text-review border-review-line' },
  REJECT: {
    label: 'Reject',
    icon: CircleSlash,
    classes: 'bg-reject-soft text-reject border-reject-line',
  },
}

export function DecisionBadge({ decision, large }: { decision: Decision; large?: boolean }) {
  const { label, icon: Icon, classes } = DECISIONS[decision]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border font-semibold tracking-wide uppercase',
        large ? 'px-2.5 py-1 text-xs' : 'px-1.5 py-0.5 text-[11px]',
        classes,
      )}
    >
      <Icon className={large ? 'size-4' : 'size-3.5'} strokeWidth={2.25} />
      {label}
    </span>
  )
}

// Where a run stands now, and who settled it.
const STATES: Record<RunState, { label: string; dot: string }> = {
  processing: { label: 'Processing', dot: 'bg-primary animate-pulse' },
  approved: { label: 'Approved by the process', dot: 'bg-approve' },
  awaiting_review: { label: 'Awaiting review', dot: 'bg-review' },
  approved_by_reviewer: { label: 'Approved by reviewer', dot: 'bg-approve' },
  rejected_by_reviewer: { label: 'Rejected by reviewer', dot: 'bg-reject' },
  rejected: { label: 'Rejected by the process', dot: 'bg-reject' },
  failed: { label: 'Failed, no decision', dot: 'bg-muted-foreground' },
}

/** Where a run stands now, including what a reviewer did after the decision. `label`
 *  replaces the usual wording (used for seeded history, which no run settled). */
export function StateLabel({ state, label }: { state: RunState; label?: string }) {
  const look = STATES[state]
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-foreground/80">
      <span className={cn('size-1.5 rounded-full', look.dot)} />
      {label ?? look.label}
    </span>
  )
}

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn('rounded-lg border bg-card', className)}>{children}</section>
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex items-end justify-between gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-reject-line bg-reject-soft p-4"
      role="alert"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-reject" />
      <div className="flex-1">
        <p className="font-medium text-reject">This could not be loaded</p>
        <p className="mt-0.5 text-foreground/80">{message}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw /> Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-md text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** A small grey tag, for facts such as "Scanned" or "Seeded history". */
export function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-px text-[11px] font-medium whitespace-nowrap text-muted-foreground',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** The small uppercase label above a group of content. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cn(
        'text-[11px] font-semibold tracking-wider text-muted-foreground uppercase',
        className,
      )}
    >
      {children}
    </p>
  )
}
