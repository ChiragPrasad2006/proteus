import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
  componentStack: string
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, componentStack: '' }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ error, componentStack: info.componentStack ?? '' })
  }

  private reset = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <main className="flex min-h-screen items-center justify-center bg-[#0C0A09] p-6 text-[#D4F268]">
        <section className="w-full max-w-2xl rounded-2xl border border-[#1C1917] bg-[#1C1917] p-6 shadow-2xl">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-[#D4F268]">Proteus encountered an error</p>
          <h1 className="mt-3 text-xl font-semibold text-white">The workspace could not be rendered.</h1>
          <pre className="mt-4 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0C0A09] p-4 font-mono text-xs text-[#D4F268]">{this.state.error.message}{this.state.error.stack ? `\n\n${this.state.error.stack}` : ''}{this.state.componentStack ? `\n\nComponent stack:${this.state.componentStack}` : ''}</pre>
          <button type="button" onClick={this.reset} className="mt-5 rounded-lg bg-[#D4F268] px-4 py-2 text-sm font-semibold text-[#0C0A09]">Reset &amp; Reload</button>
        </section>
      </main>
    )
  }
}
