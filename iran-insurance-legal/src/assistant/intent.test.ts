import { describe, expect, it } from 'vitest'
import type { ArchiveState } from '@/api/types'
import { parseNavigation } from './intent'

const state = { cases: [{ id: '1404705025', number: '1404705025', title: 'بازیافت خسارت' }] } as unknown as ArchiveState

describe('parseNavigation', () => {
  it('opens a section asked for explicitly, in Persian', () => {
    expect(parseNavigation('پرونده‌ها را باز کن')).toMatchObject({ section: 'cases' })
    expect(parseNavigation('صف بازبینی را نشان بده')).toMatchObject({ section: 'review' })
    expect(parseNavigation('برو به داشبورد')).toMatchObject({ section: 'dashboard' })
  })

  it('opens a section asked for in English', () => {
    expect(parseNavigation('open events')).toMatchObject({ section: 'events' })
  })

  it('opens a case by its number, Persian digits included', () => {
    expect(parseNavigation('پرونده ۱۴۰۴۷۰۵۰۲۵', state)).toMatchObject({ section: 'cases', record: '1404705025' })
    expect(parseNavigation('1404705025', state)).toMatchObject({ section: 'cases', record: '1404705025' })
  })

  it('leaves questions and filings to the engine router', () => {
    expect(parseNavigation('ماده ۳۰ قانون بیمه دربارهٔ جانشینی بیمه‌گر چه می‌گوید؟')).toBeNull()
    expect(parseNavigation('چند پرونده شخص ثالث داریم؟')).toBeNull()
    expect(parseNavigation('صورت‌جلسهٔ رسیدگی شعبهٔ ۳ دادگاه حقوقی تهران؛ خواهان شرکت سهامی بیمه ایران با وکالت آقای رضا کریمی')).toBeNull()
  })
})
