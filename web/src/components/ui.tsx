import { Check, ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
        {subtitle && <p className="text-sm text-gray-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className, bodyClassName }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-gray-200 bg-white", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 px-4 pt-4">
          {title && <h2 className="text-lg font-semibold text-gray-900">{title}</h2>}
          {actions}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function KpiTile({ icon, label, value, footer }: { icon: ReactNode; label: string; value: ReactNode; footer?: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-100 p-1">
      <div className="rounded-lg border-b border-gray-200 bg-white p-4">
        <div className="grid size-10 place-items-center rounded-lg border border-gray-200 text-gray-900">{icon}</div>
        <div className="mt-4 text-sm text-gray-500">{label}</div>
        <div className="tabular text-xl font-semibold text-gray-900">{value}</div>
      </div>
      {footer && <div className="flex justify-between px-3 py-2 text-xs text-gray-500">{footer}</div>}
    </div>
  );
}

type Status = "verificado" | "sin-verificar" | "sin-comprobante" | "auto" | "posible";
const STATUS: Record<Status, { label: string; dot: string }> = {
  verificado: { label: "Verificado", dot: "bg-success" },
  "sin-verificar": { label: "Sin verificar", dot: "bg-warning" },
  "sin-comprobante": { label: "Sin comprobante", dot: "bg-error" },
  auto: { label: "Vinculado automáticamente", dot: "bg-info" },
  posible: { label: "Posible coincidencia", dot: "bg-warning" },
};
export function StatusTag({ status, label }: { status: Status; label?: string }) {
  const s = STATUS[status];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-gray-200 bg-white px-2 py-0.5 text-xs font-semibold text-gray-900">
      <span className={cx("size-1.5 rounded-full", s.dot)} />
      {label ?? s.label}
    </span>
  );
}

export function Button({ variant = "default", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "default" | "ghost" }) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-2 text-sm font-medium transition-colors active:translate-y-px disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" && "h-9 rounded-lg bg-primary px-3 text-white hover:bg-primary-deep",
        variant === "default" && "h-9 rounded-lg border border-gray-300 bg-white px-3 text-gray-700 hover:bg-gray-50",
        variant === "ghost" && "size-8 rounded-md text-gray-900/70 hover:bg-gray-100",
        className,
      )}
    />
  );
}

/** Same look as Button, for links. */
export const buttonClass = (variant: "primary" | "default" = "default") =>
  cx(
    "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors active:translate-y-px",
    variant === "primary" ? "bg-primary text-white hover:bg-primary-deep" : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
  );

const fieldClass =
  "h-9 rounded-lg border border-gray-300 bg-white px-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary";

export function Input({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={cx(fieldClass, className)} />;
}

export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...p} className={cx(fieldClass, "pr-8", className)}>
      {children}
    </select>
  );
}

export function SidePanel({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-md" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-menu">
        <div className="flex items-center justify-between border-b border-gray-200 p-4">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Cerrar">
            <X size={18} />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-gray-500">{children}</div>;
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-gray-400">Cargando…</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg border border-error bg-error-subtle p-3 text-sm text-error">
      No se pudo cargar la información. {error instanceof Error ? `(${error.message})` : null}
    </div>
  );
}

/** Renders FTS snippets: \u0002 … \u0003 mark a hit. Never uses innerHTML. */
export function Snippet({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const re = /\u0002([^\u0003]*)\u0003/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    parts.push(text.slice(last, m.index));
    parts.push(<mark key={m.index}>{m[1]}</mark>);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

export interface MultiOption {
  value: string;
  label: string;
  group?: string;
}

/** Dropdown with checkboxes. An empty selection means "all". */
export function MultiSelect({ label, allLabel, plural, options, value, onChange, className }: {
  label: string;
  allLabel: string;
  plural: string; // noun for the summary, e.g. "períodos" -> "3 períodos"
  options: MultiOption[];
  value: string[];
  onChange: (v: string[]) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = new Set(value);
  const toggle = (v: string) => onChange(selected.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  const summary =
    value.length === 0
      ? allLabel
      : value.length === 1
        ? (options.find((o) => o.value === value[0])?.label ?? value[0])
        : `${value.length} ${plural}`;

  let lastGroup: string | undefined;
  return (
    <div ref={ref} className={cx("relative", className)}>
      <button
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cx(fieldClass, "inline-flex w-full items-center justify-between gap-2 text-left", value.length > 0 && "border-primary")}
      >
        <span className="truncate">{summary}</span>
        <ChevronDown size={14} className="shrink-0 text-gray-400" />
      </button>
      {open && (
        <div
          id={id}
          role="listbox"
          aria-multiselectable="true"
          className="absolute left-0 z-30 mt-1 max-h-80 w-64 md:left-auto md:right-0 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
        >
          <button
            type="button"
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-gray-50 disabled:text-gray-400"
            disabled={value.length === 0}
            onClick={() => onChange([])}
          >
            {allLabel}
            {value.length === 0 && <Check size={14} className="text-primary" />}
          </button>
          <div className="my-1 border-t border-gray-200" />
          {options.map((o) => {
            const header = o.group && o.group !== lastGroup ? o.group : null;
            lastGroup = o.group;
            const on = selected.has(o.value);
            return (
              <div key={o.value}>
                {header && <div className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-gray-400">{header}</div>}
                <label role="option" aria-selected={on} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm text-gray-900 hover:bg-gray-50">
                  <input type="checkbox" checked={on} onChange={() => toggle(o.value)} className="size-4 accent-[var(--color-primary)]" />
                  <span className="truncate">{o.label}</span>
                </label>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
