import { describe, expect, it } from 'vitest'
import { compactRial, fa, rial } from './format'

describe('Persian formatting', () => {
  it('never shows Latin digits', () => {
    expect(fa(1404)).toBe('۱٬۴۰۴')
    expect(fa('1403/08/10')).toBe('۱۴۰۳/۰۸/۱۰')
    expect(fa(null)).toBe('—')
  })
  it('formats rial amounts', () => {
    expect(rial(2250000000)).toBe('۲٬۲۵۰٬۰۰۰٬۰۰۰ ریال')
    expect(rial(0)).toBe('—')
    expect(compactRial(2250000000)).toBe('۲٫۳ میلیارد ریال')
  })
})
