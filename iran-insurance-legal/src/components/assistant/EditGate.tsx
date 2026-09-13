import { motion } from 'framer-motion'
import { Check, CircleCheck, PenLine, X } from 'lucide-react'
import { useState } from 'react'
import { cancelEdit, confirmEdit } from '@/assistant/runtime'
import type { Message } from '@/assistant/types'
import { fa } from '@/lib/format'
import { Button } from '@/components/ui/button'
import { KV } from '@/components/shared/Bits'
import { useShell } from '@/state/shell'

/**
 * The confirmation an agent's edit has to pass before it reaches the archive
 * — Streamlit's `_edit_gate`. `propose_edit` wrote nothing: one field, the
 * current value beside the new one, and only «تأیید و ثبت» applies it. Bulk
 * field editing belongs to section ۱۷ (ویرایش مدخل).
 */
export function EditGate({ m }: { m: Message }) {
  const proposal = m.result?.pending_edit
  const open = useShell((s) => s.open)
  const [busy, setBusy] = useState(false)
  if (!proposal) return null

  const openEntry = () => open('editor', { record: proposal.entry_id, label: 'ویرایش مدخل', origin: 'tab' })

  if (m.editState === 'done') {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-emerald-300/15 bg-emerald-300/[.05] px-3 py-2 text-[12px] text-emerald-100/85">
        <CircleCheck className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1">ثبت شد — {proposal.field_fa}: {fa(proposal.new_text)}</span>
        <Button size="sm" variant="ghost" className="h-7 text-emerald-100/80" onClick={openEntry}><PenLine className="h-3.5 w-3.5" /> مدخل</Button>
      </div>
    )
  }
  if (m.editState === 'cancelled') return <div className="text-[12px] text-white/45">ویرایش انجام نشد — چیزی در آرشیو تغییر نکرد.</div>

  const verb = proposal.op === 'append' ? 'افزودن به' : 'تغییر'
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="suggested space-y-2 rounded-3xl px-4 pb-4 pt-3.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-violet-200/85"><PenLine className="h-3.5 w-3.5" /> پیشنهاد ویرایش — هنوز ثبت نشده</div>
      <div className="text-sm font-medium text-white/90">{verb} «{proposal.field_fa}»</div>
      <KV rows={[
        ['مدخل', <button key="entry" onClick={openEntry} className="hover:text-white hover:underline">{fa(proposal.entry_title || proposal.entry_id.slice(0, 8))}</button>],
        ['مقدار فعلی', fa(proposal.old_text)],
        ['مقدار جدید', <b key="new" className="font-medium text-white">{fa(proposal.new_text)}</b>],
      ]} />
      {m.restored ? (
        <div className="text-[11.5px] leading-6 text-white/45">این پیشنهاد از گفتگوی پیشین است و مدخل ممکن است از آن زمان تغییر کرده باشد — برای ویرایش، دوباره بخواهید.</div>
      ) : (
        <div className="flex gap-2 pt-1">
          <Button size="sm" variant="approve" disabled={busy} onClick={async () => { setBusy(true); await confirmEdit(m.id); setBusy(false) }}>
            <Check className="h-3.5 w-3.5" /> تأیید و ثبت
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => cancelEdit(m.id)}><X className="h-3.5 w-3.5" /> انصراف</Button>
        </div>
      )}
    </motion.div>
  )
}
