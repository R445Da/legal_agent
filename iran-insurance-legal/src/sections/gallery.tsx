import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { api } from '@/api/endpoints'
import { ask } from '@/assistant/runtime'
import type { OrbState } from '@/assistant/types'
import { fa } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { SECTIONS, TONES } from '@/sections/registry'
import { AIOrb, ORB_LABEL } from '@/components/assistant/AIOrb'
import { Waveform } from '@/components/assistant/Waveform'
import { WhyThis } from '@/components/assistant/WhyThis'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Pill, Stat } from '@/components/ui/misc'
import { CaseNo, Chips, KV, Timeline } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/** ۱۸ نمایشگاه طراحی — the design vocabulary of this front end, and the demo stages as data. */
export function GalleryView({ ws }: { ws: WorkspaceTab }) {
  usePublishContext('gallery', {})
  if (ws.tab === 'tokens') return <Tokens />
  if (ws.tab === 'components') return <Components />
  return <Stages />
}

function Stages() {
  const stages = useQuery({ queryKey: ['stages'], queryFn: api.demoStages, staleTime: Infinity })
  const { open, goHome } = useShell()
  if (stages.error) return <LoadError error={stages.error} />
  if (!stages.data) return <Skeleton />
  return (
    <>
      <PageHeader eyebrow="۱۸ · نمایشگاه طراحی" title="مراحل نمایش" summary="نمایش به‌صورت داده (app/demo/stages.py): هر مرحله چند پیام با نوع و حالت ثبتی که باید با آن فرستاده شود. scripts/demo_stages.py همین‌ها را آزمون می‌کند." />
      <div className="mt-6 space-y-4">
        {stages.data.stages.map((st, i) => (
          <Card key={st.id} className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><div className="text-[11px] text-white/35">مرحلهٔ {fa(i + 1)}</div><div className="text-[15px] font-semibold">{st.title}</div><p className="mt-1 max-w-3xl text-[12.5px] leading-6 text-white/50">{st.blurb}</p></div>
              <div className="flex flex-wrap gap-1.5">{st.show.map((s) => { const def = SECTIONS.find((x) => x.id === s); return def ? <Button key={s} size="sm" variant="ghost" onClick={() => open(def.id)}>{def.num} {def.title}</Button> : null })}</div>
            </div>
            <ol className="mt-3 space-y-2">
              {st.prompts.map((p, j) => (
                <li key={j} className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/[.06] bg-white/[.02] px-3 py-2">
                  <span className="min-w-0 flex-1 whitespace-pre-line text-[12.5px] leading-6 text-white/80">{p.text}</span>
                  {p.intent && <Pill tone="info">{p.intent}</Pill>}{p.mode && <Pill tone="suggest">{p.mode}</Pill>}
                  <Button size="sm" onClick={() => { if (p.mode) useSettings.getState().set({ runMode: p.mode }); goHome(); void ask(p.text, 'home', p.intent ?? undefined) }}><Play className="h-3.5 w-3.5 -scale-x-100" /> اجرا</Button>
                </li>
              ))}
            </ol>
          </Card>
        ))}
      </div>
    </>
  )
}

function Tokens() {
  const ink = [['ink-950', '#07080d'], ['ink-900', '#090b11'], ['ink-850', '#0b0d14'], ['ink-800', '#10121c'], ['ink-700', '#161927']]
  return (
    <>
      <PageHeader eyebrow="۱۸ · نمایشگاه طراحی" title="نشانه‌های طراحی" summary="زمینهٔ جوهری، مش ملایم نیلی/فیروزه‌ای، شیشهٔ کم‌مصرف، کره‌ی مخروطی — راست‌به‌چپ از پایه." />
      <Card className="mt-6 p-5">
        <div className="mb-3 text-sm font-medium">زمینه</div>
        <div className="flex flex-wrap gap-3">{ink.map(([k, v]) => <div key={k} className="w-28 text-center"><div className="h-12 rounded-xl border border-white/10" style={{ background: v }} /><div className="ltr mt-1 font-mono text-[10.5px] text-white/45">{k}<br />{v}</div></div>)}</div>
        <div className="mb-3 mt-6 text-sm font-medium">رنگ‌های بخش‌ها</div>
        <div className="flex flex-wrap gap-3">{Object.entries(TONES).map(([k, t]) => <div key={k} className="w-28 text-center"><div className="h-12 rounded-xl border border-white/10" style={{ background: t.hex }} /><div className="ltr mt-1 font-mono text-[10.5px] text-white/45">{k}<br />{t.hex}</div></div>)}</div>
        <div className="mb-2 mt-6 text-sm font-medium">حروف</div>
        <div className="space-y-1"><div className="text-4xl font-extrabold">وزیرمتن — عنوان</div><div className="text-[15px] text-white/75">متن بدنه با ارقام فارسی: {fa(1404705025)} · {fa(2250000000)} ریال</div><div className="ltr font-mono text-sm text-white/60">JetBrains Mono — ids, sources, code</div></div>
      </Card>
      <Card className="mt-5 p-5">
        <div className="mb-3 text-sm font-medium">حالت‌های پیشنهاد و ثبت</div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="suggested rounded-2xl p-4 text-[12.5px] text-violet-50/90">پیشنهاد دستیار — لبهٔ خط‌چین بنفش، تا تأیید شما هرگز شبیه دادهٔ ثبت‌شده نیست.</div>
          <div className="rounded-2xl border border-emerald-300/20 bg-emerald-400/[.04] p-4 text-[12.5px] text-emerald-50/90">ثبت‌شده — لبهٔ سبز ممتد، پس از اجرای تأییدشده.</div>
        </div>
      </Card>
    </>
  )
}

function Components() {
  const states: OrbState[] = ['idle', 'listening', 'processing', 'working', 'responding', 'awaiting', 'completed', 'error']
  return (
    <>
      <PageHeader eyebrow="۱۸ · نمایشگاه طراحی" title="اجزا" summary="اجزای مشترک این رابط، روی دادهٔ نمونه." />
      <Card className="mt-6">
        <CardHeader title="کره‌ی دستیار — هشت حالت" subtitle="وضعیت را نشان می‌دهد، هرگز استدلال را" />
        <div className="grid grid-cols-2 gap-6 px-5 pb-6 sm:grid-cols-4">{states.map((s) => <div key={s} className="flex flex-col items-center gap-3"><AIOrb state={s} size="md" level={s === 'listening' ? 0.5 : 0} /><span className="text-[11.5px] text-white/55">{ORB_LABEL[s]}</span></div>)}</div>
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3"><Stat label="پرونده‌ها" value={fa(120)} /><Stat label="در صف بازبینی" value={fa(3)} tone="bad" /></div>
          <div className="flex flex-wrap gap-2"><Pill tone="good" dot>کامل</Pill><Pill tone="warn">ناقص</Pill><Pill tone="bad">ناموفق</Pill><Pill tone="info">جاری</Pill><Pill tone="suggest">پیشنهاد</Pill></div>
          <Chips tone="teal" items={['شخص ثالث', 'بازیافت', 'دیه']} />
          <div className="flex items-center gap-3"><CaseNo value="1404705025" /><Waveform className="h-6" /></div>
          <WhyThis signals={['شمارهٔ پرونده در متن شما', 'زمینه: پروندهٔ باز در «پرونده‌ها»']} />
        </Card>
        <Card className="p-5">
          <KV rows={[['نوع دعوا', 'جانشینی / بازیافت'], ['رشتهٔ بیمه', 'آتش‌سوزی'], ['وضعیت', 'تجدیدنظر']]} />
          <div className="mt-4"><Timeline items={[{ date: '1403/08/10', title: 'ثبت دادخواست' }, { date: '1404/01/10', title: 'صدور رأی', detail: 'قرار رد دعوا به علت مرور زمان', tone: 'manual', source: 'یادآور' }]} /></div>
        </Card>
      </div>
    </>
  )
}
