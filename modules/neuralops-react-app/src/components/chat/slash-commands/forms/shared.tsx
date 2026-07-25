/**
 * Shared UI primitives used by all slash-command forms.
 */
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import type { TestResult } from "@/types";

// ── Field ─────────────────────────────────────────────────────────────────────

export function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-foreground">
        {label}
        {required && <span className="ml-0.5 text-destructive">*</span>}
      </label>
      {children}
    </div>
  );
}

// ── Input ─────────────────────────────────────────────────────────────────────

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={
        "h-8 w-full rounded-md border border-input bg-background px-3 text-sm outline-none " +
        "focus:ring-2 focus:ring-ring placeholder:text-muted-foreground " +
        (props.className ?? "")
      }
    />
  );
}

// ── Select ────────────────────────────────────────────────────────────────────

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={
        "h-8 w-full rounded-md border border-input bg-background px-3 text-sm outline-none " +
        "focus:ring-2 focus:ring-ring " +
        (props.className ?? "")
      }
    />
  );
}

// ── Textarea ──────────────────────────────────────────────────────────────────

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={3}
      {...props}
      className={
        "w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none " +
        "focus:ring-2 focus:ring-ring resize-none placeholder:text-muted-foreground " +
        (props.className ?? "")
      }
    />
  );
}

// ── TestBadge ─────────────────────────────────────────────────────────────────

export function TestBadge({
  result,
  loading,
}: {
  result: TestResult | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Testing…
      </div>
    );
  }
  if (!result) return null;

  if (result.ok) {
    return (
      <div className="rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs">
        <div className="flex items-center gap-1.5 font-medium text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Connected · {result.latency_ms}ms
        </div>
        {result.response && (
          <p className="mt-1 text-muted-foreground line-clamp-2">{result.response}</p>
        )}
        {result.tools && result.tools.length > 0 && (
          <p className="mt-1 text-muted-foreground">
            Tools: {result.tools.join(", ")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-destructive">
        <XCircle className="h-3.5 w-3.5" />
        Failed
      </div>
      {result.error && (
        <p className="mt-1 text-muted-foreground line-clamp-3 font-mono">{result.error}</p>
      )}
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

export function Row({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>;
}
