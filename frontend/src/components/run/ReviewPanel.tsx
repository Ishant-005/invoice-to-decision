// The reviewer's controls on a REVIEW run: a required comment, then approve or reject. When
// the purchase order was not confirmed by the process, the reviewer confirms or chooses it.

import { Check, X } from 'lucide-react'
import { useState } from 'react'

import { Eyebrow } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { type MatchResult, type PurchaseOrder, resolveRun, type RulesResult, type RunDetail } from '@/lib/api'
import { fromPaise, inr, toPaise } from '@/lib/format'
import { useApi } from '@/lib/useApi'

export function ReviewPanel({ run, onResolved }: { run: RunDetail; onResolved: (run: RunDetail) => void }) {
  const match = run.stages.find((stage) => stage.stage === 'match')?.result as MatchResult | null
  const rules = run.stages.find((stage) => stage.stage === 'rules')?.result as RulesResult | null
  // The reviewer picks the PO whenever the process did not confirm one from the invoice.
  const mustChoosePO = match !== null && match.vendor_id !== null && match.po_match_type !== 'explicit_verified'
  // Today's balances, because an approval is booked against the PO as it stands now.
  const orders = useApi<PurchaseOrder[]>('/api/purchase-orders')
  const vendorOrders = orders.data?.filter((po) => po.vendor_id === match?.vendor_id) ?? []

  const [poId, setPoId] = useState(run.po_id ?? '')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const hasComment = comment.trim() !== ''
  const canApprove = run.pretax_amount !== null && poId !== ''
  const suggested = match?.po_match_type.startsWith('implied') ? match.po_id : null
  const po = orders.data?.find((order) => order.id === poId) ?? null

  async function resolve(action: 'approve' | 'reject') {
    if (!hasComment) return
    setBusy(action)
    setError(null)
    try {
      onResolved(await resolveRun(run.id, action, comment, action === 'approve' && mustChoosePO ? poId : undefined))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The decision could not be saved.')
      setBusy(null)
    }
  }

  return (
    <div className="mt-4 border-t pt-3.5">
      <Eyebrow>Reviewer's decision</Eyebrow>

      {mustChoosePO && (
        <label className="mt-2 block">
          <span className="text-[13px] text-foreground/80">Purchase order to book against</span>
          <select
            value={poId}
            onChange={(event) => setPoId(event.target.value)}
            className="num mt-1 block h-8 w-full rounded-md border border-input bg-card px-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {poId === '' && <option value="">Choose a purchase order…</option>}
            {/* Until the list has loaded, the suggested PO is the only choice. */}
            {vendorOrders.length === 0 && poId !== '' && <option value={poId}>{poId}</option>}
            {vendorOrders.map((order) => (
              <option key={order.id} value={order.id}>
                {order.id} · {inr(order.remaining)} remaining{order.id === suggested ? ' · suggested' : ''}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="mt-2.5 block">
        <span className="text-[13px] text-foreground/80">Comment (required to approve or reject)</span>
        <Textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder="Why are you approving or rejecting?"
          rows={2}
          maxLength={2000}
          className="mt-1 min-h-14 bg-card"
        />
      </label>

      {error && (
        <p className="mt-2 text-[13px] text-reject" role="alert">
          {error}
        </p>
      )}

      {/* Two equal choices: the same size and weight, neither one pre-selected. Both stay
          disabled until there is a comment. */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button
          variant="outline"
          disabled={!hasComment || busy !== null || !canApprove}
          onClick={() => resolve('approve')}
          className="border-approve/50 bg-card font-semibold text-approve hover:bg-approve-soft hover:text-approve disabled:opacity-60 dark:border-approve/50 dark:bg-card dark:hover:bg-approve-soft"
        >
          <Check /> {busy === 'approve' ? 'Saving…' : mustChoosePO && poId ? `Approve on ${poId}` : 'Approve'}
        </Button>
        <Button
          variant="outline"
          disabled={!hasComment || busy !== null}
          onClick={() => resolve('reject')}
          className="border-reject/50 bg-card font-semibold text-reject hover:bg-reject-soft hover:text-reject disabled:opacity-60 dark:border-reject/50 dark:bg-card dark:hover:bg-reject-soft"
        >
          <X /> {busy === 'reject' ? 'Saving…' : 'Reject'}
        </Button>
      </div>

      <div className="mt-2.5 space-y-1.5 text-xs leading-relaxed text-foreground/80">
        <p>{approveConsequence(run, po, rules)}</p>
        <p>Rejecting books nothing against any purchase order. A corrected invoice can be submitted again.</p>
      </div>
    </div>
  )
}

/**
 * What approving would do, in the figures of this invoice: how much is booked against which
 * purchase order, where that leaves the PO, and any risk the findings point to.
 */
function approveConsequence(run: RunDetail, po: PurchaseOrder | null, rules: RulesResult | null): string {
  if (run.pretax_amount === null)
    return 'Approving is not possible: the amount before tax is not known, so nothing can be booked against a purchase order.'
  if (po === null) return `Approving adds ${inr(run.pretax_amount)} before tax to the purchase order you choose.`

  // Exact arithmetic in whole paise, against the PO's balance as it stands now.
  const after = toPaise(po.billed_to_date) + toPaise(run.pretax_amount)
  const left = toPaise(po.value) - after
  let text = `Approving adds ${inr(run.pretax_amount)} before tax to ${po.id}`
  if (left < 0n) text += ` and takes it ${inr(fromPaise(-left))} over its value.`
  else if (left === 0n) text += `, which is then fully billed (${inr(po.value)} of ${inr(po.value)}).`
  else text += `, leaving ${inr(fromPaise(left))} of its ${inr(po.value)} value unbilled.`

  const duplicate = rules?.duplicates[0]
  if (duplicate && run.gross_amount)
    text += ` If this is the same bill as ${duplicate.invoice_number ?? 'the earlier invoice'}, ${inr(run.gross_amount)} including tax is paid twice.`
  if (run.gross_amount === null) text += ' The total could not be read, so the amount to pay is not confirmed by the document.'
  return text
}
