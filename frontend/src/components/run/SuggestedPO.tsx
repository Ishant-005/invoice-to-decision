// For an invoice that quotes no purchase order: the purchase orders the Match stage scored,
// with the evidence for each, so a person can confirm the suggestion.

import { Check, X } from 'lucide-react'

import { Eyebrow, Panel, Tag } from '@/components/common'
import type { MatchResult, PurchaseOrder, Rules } from '@/lib/api'
import { day, inr, quantity } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

export function SuggestedPO({ match }: { match: MatchResult }) {
  const rules = useApi<Rules>('/api/config/rules')
  const orders = useApi<PurchaseOrder[]>('/api/purchase-orders')
  const strongAt = rules.data?.match.implied_po_strong_score
  const m = rules.data?.match

  return (
    <Panel>
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <h2 className="font-semibold">
          {match.po_match_type === 'implied_single' ? 'Suggested purchase order' : 'Purchase orders that could fit'}
        </h2>
        <p className="ml-auto text-xs text-muted-foreground">
          The invoice quotes no purchase order, so the Match stage scored each open purchase order of{' '}
          {match.vendor_name}. A suggestion is never approved without a person.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 p-4">
        {match.candidates.map((candidate) => {
          const po = orders.data?.find((order) => order.id === candidate.po_id)
          const suggested = candidate.strong
          // The three tests, in the order the backend lists its evidence.
          const tests = [candidate.amount_fits, candidate.description_similarity >= (m?.line_match_min_score ?? 70), candidate.date_ok]
          const points = m ? [m.implied_po_points_amount_fits, m.implied_po_points_description, m.implied_po_points_date] : []
          return (
            <div key={candidate.po_id} className={cn('rounded-md border px-4 py-3', suggested ? 'border-primary/40 bg-accent/40' : 'opacity-80')}>
              <div className="flex items-center gap-2.5">
                <span className="num text-base font-semibold">{candidate.po_id}</span>
                {suggested ? <Tag className="border-primary/30 bg-accent text-accent-foreground">Suggested</Tag> : <Tag>Considered, does not fit</Tag>}
                <span className="ml-auto text-right">
                  <span className="num text-base font-semibold">{candidate.score.toFixed(0)}</span>
                  <span className="num text-xs text-muted-foreground"> / 100</span>
                  {strongAt !== undefined && <span className="block text-[11px] text-muted-foreground">{strongAt} or more is a strong fit</span>}
                </span>
              </div>

              <ul className="mt-2.5 space-y-1.5">
                {candidate.evidence.map((text, index) => (
                  <li key={text} className="flex gap-2">
                    {tests[index] ? (
                      <Check className="mt-0.5 size-3.5 shrink-0 text-approve" strokeWidth={3} />
                    ) : (
                      <X className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" strokeWidth={3} />
                    )}
                    <span className="first-letter:uppercase">
                      {text}
                      {points[index] !== undefined && (
                        <span className="text-xs text-muted-foreground">
                          {' '}
                          (up to {points[index]} points{index === 1 && `; ${candidate.description_similarity.toFixed(0)}% similar`})
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>

              {po && (
                <div className="mt-3 border-t pt-2.5">
                  <Eyebrow>What {po.id} covers</Eyebrow>
                  <ul className="mt-1 space-y-0.5 text-[13px]">
                    {po.lines.map((line) => (
                      <li key={line.line_no} className="flex justify-between gap-3">
                        <span>
                          <span className="num">{quantity(line.quantity)}</span> × {line.description} at <span className="num">{inr(line.unit_price)}</span>
                        </span>
                        <span className="num">{inr(line.amount)}</span>
                      </li>
                    ))}
                  </ul>
                  {/* Only facts that never change. The balance at the time of the run is in the
                      evidence above; today's balance may differ. */}
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Dated {day(po.po_date)} · value <span className="num">{inr(po.value)}</span> before tax
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
