import { AlertTriangle } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

/** Catches a crash while rendering a screen and offers a reload, instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Screen crashed", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // Navigating to another page clears the error.
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="glass mx-auto mt-10 max-w-md rounded-2xl p-8 text-center">
        <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-red-500/10"><AlertTriangle className="h-6 w-6 text-red-500" aria-hidden /></span>
        <h1 className="text-base font-semibold text-slate-900">Something went wrong on this screen</h1>
        <p className="mt-1 text-sm text-slate-600">Your data is safe. Reload the page to continue; if it happens again, tell your administrator what you were doing.</p>
        <button type="button" onClick={() => window.location.reload()}
          className="mt-4 inline-flex h-9 items-center rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800">Reload page</button>
      </div>
    );
  }
}
