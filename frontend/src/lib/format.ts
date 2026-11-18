// How values are shown. Money is handled as text and whole paise, never as a floating-point
// number, so what is displayed is exactly what the backend calculated.

/** "106200.00" -> "₹1,06,200" (Indian grouping). Paise are shown only when they are not zero. */
export function inr(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const negative = amount.startsWith('-')
  const [whole, paise = ''] = amount.replace('-', '').split('.')
  // Indian grouping: the last three digits, then groups of two.
  const lastThree = whole.slice(-3)
  const rest = whole.slice(0, -3)
  const grouped = rest ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + lastThree : lastThree
  const decimals = /^0*$/.test(paise) ? '' : '.' + paise.padEnd(2, '0').slice(0, 2)
  return `${negative ? '−' : ''}₹${grouped}${decimals}`
}

/** Money text to whole paise, so amounts can be added and subtracted exactly. */
export function toPaise(amount: string): bigint {
  const negative = amount.startsWith('-')
  const [whole, paise = ''] = amount.replace('-', '').split('.')
  const value = BigInt(whole || '0') * 100n + BigInt(paise.padEnd(2, '0').slice(0, 2) || '0')
  return negative ? -value : value
}

/** Whole paise back to money text ("180000.00"). */
export function fromPaise(paise: bigint): string {
  const negative = paise < 0n
  const absolute = negative ? -paise : paise
  const text = `${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
  return negative ? '-' + text : text
}

/** A share between 0 and 1, used only to draw the width of a bar (never shown as a figure). */
export function share(part: string, whole: string): number {
  const total = toPaise(whole)
  if (total <= 0n) return 0
  return Math.max(0, Math.min(1, Number((toPaise(part) * 10000n) / total) / 10000))
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-11-14" -> "14 Nov 2026". Done by hand so no time zone can shift the day. */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`
}

/** A moment in time (UTC from the server) in the viewer's local time: "18 Nov, 21:41". */
export function moment(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${date.getDate()} ${MONTHS[date.getMonth()]}, ${time}`
}

/** A measured duration: "0.2 ms", "21.8 ms", "4.07 s". Never rounded to zero. */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms.toFixed(1)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

/** "1000" stays "1000", "2.50" -> "2.5": a quantity without trailing zeros. */
export function quantity(text: string | null | undefined): string {
  if (!text) return '—'
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text
}

export function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
