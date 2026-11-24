import { BookOpen, Building2, ChartColumn, Presentation, ClipboardCheck, FileText, HelpCircle, LayoutDashboard, Menu, MessageSquare, NotebookPen, Receipt, Search, Sparkles } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { formatDate } from "../lib/format";
import { Button } from "./ui";

const NAV: { section: string; items: { to: string; label: string; icon: ReactNode; end?: boolean }[] }[] = [
  {
    section: "General",
    items: [
      { to: "/", label: "Inicio", icon: <LayoutDashboard size={18} />, end: true },
      { to: "/buscar", label: "Buscar", icon: <Search size={18} /> },
      { to: "/preguntar", label: "Preguntar", icon: <Sparkles size={18} /> },
      { to: "/comentarios", label: "Comentarios", icon: <MessageSquare size={18} /> },
    ],
  },
  {
    section: "Documentos",
    items: [
      { to: "/gastos", label: "Gastos", icon: <Receipt size={18} /> },
      { to: "/comprobantes", label: "Comprobantes", icon: <FileText size={18} /> },
      { to: "/analisis", label: "Análisis", icon: <ChartColumn size={18} /> },
      { to: "/observaciones", label: "Observaciones", icon: <ClipboardCheck size={18} /> },
      { to: "/asamblea", label: "Asamblea", icon: <Presentation size={18} /> },
      { to: "/actas", label: "Actas", icon: <NotebookPen size={18} /> },
      { to: "/reglamento", label: "Reglamento", icon: <BookOpen size={18} /> },
    ],
  },
  {
    section: "Ayuda",
    items: [{ to: "/como-funciona", label: "Cómo funciona", icon: <HelpCircle size={18} /> }],
  },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex h-full flex-col gap-6 px-4 py-5">
      <div className="flex items-center gap-2 px-2">
        <div className="grid size-8 place-items-center rounded-lg bg-primary text-white">
          <Building2 size={18} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-gray-900">Torre 3</div>
          <div className="text-xs text-gray-500">Portal de vecinos</div>
        </div>
      </div>
      {NAV.map((g) => (
        <div key={g.section} className="space-y-1">
          <div className="px-2 text-xs uppercase tracking-wide text-gray-500">{g.section}</div>
          {g.items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex h-9 items-center gap-2 rounded-lg px-2 text-sm ${
                  isActive
                    ? "bg-gray-100 font-semibold text-primary shadow-xs ring-1 ring-inset ring-gray-200"
                    : "text-gray-700 hover:bg-gray-100"
                }`
              }
            >
              {it.icon}
              {it.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-auto flex items-center gap-2 px-2">
        <div className="grid size-8 place-items-center rounded-md border border-gray-200 bg-gray-100 text-sm font-semibold text-gray-700">V</div>
        <div className="text-xs text-gray-500">Vecino/a de Torre 3</div>
      </div>
    </nav>
  );
}

export function AppShell() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) navigate(`/buscar?q=${encodeURIComponent(q.trim())}`);
  };
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[260px] shrink-0 lg:block print:hidden">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="relative h-full w-[260px] bg-gray-50">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1 p-2 print:p-0">
        <div className="min-h-[calc(100vh-1rem)] rounded-lg bg-white shadow print:min-h-0 print:shadow-none">
          <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-2 md:px-8 print:hidden">
            <Button variant="ghost" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Abrir menú">
              <Menu size={18} />
            </Button>
            <form onSubmit={onSearch} className="relative max-w-sm flex-1">
              <Search size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-gray-400" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Buscar en documentos…"
                className="h-9 w-full rounded-lg border border-gray-300 pr-3 pl-9 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </form>
            <span className="ml-auto hidden text-xs text-gray-400 sm:block">{formatDate(new Date())}</span>
          </div>
          <main className="space-y-4 px-4 py-6 md:px-8 print:p-0">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
