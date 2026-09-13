import { Component, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

/** One broken section must not blank the workspace: show the error, offer a retry. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="mx-auto max-w-lg py-20 text-center">
        <div className="text-sm font-medium text-white/85">این بخش با خطا روبه‌رو شد</div>
        <div className="ltr mt-2 break-words font-mono text-[11px] text-rose-200/70">{this.state.error.message}</div>
        <Button className="mt-4" onClick={() => this.setState({ error: null })}>تلاش دوباره</Button>
      </div>
    )
  }
}
