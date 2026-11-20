import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps { children: ReactNode }
interface ErrorBoundaryState { error: Error | null; componentStack: string }
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, componentStack: '' }
  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { this.setState({ error, componentStack: info.componentStack ?? '' }) }
  private reset = () => { window.location.reload() }
  render() {
    if (!this.state.error) return this.props.children
    return <main className="flex min-h-screen items-center justify-center bg-cobalt p-6 text-paper"><section className="w-full max-w-2xl rounded-sm border border-hairline bg-cobalt-deep p-6"><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ember">Proteus encountered an error</p><h1 className="mt-3 font-display text-2xl">The workspace could not be rendered.</h1><pre className="mt-4 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-cobalt p-4 font-mono text-[11px] text-foam">{this.state.error.message}{this.state.error.stack ? `\n\n${this.state.error.stack}` : ''}{this.state.componentStack ? `\n\nComponent stack:${this.state.componentStack}` : ''}</pre><button type="button" onClick={this.reset} className="mt-5 rounded-pill bg-paper px-5 py-2.5 text-sm font-medium text-ink">Reset & Reload</button></section></main>
  }
}
