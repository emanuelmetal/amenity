import { useQuery } from "@tanstack/react-query";
import { BookOpen, CalendarDays, ListChecks, Receipt, Wallet } from "lucide-react";
import { Link } from "react-router";
import { api, type Period, type Rubro } from "../lib/api";
import { formatDate, formatMoney, formatMoneyRound, formatPeriod } from "../lib/format";
import { buttonClass, Card, ErrorBox, KpiTile, Loading, PageHeader } from "../components/ui";

function Delta({ current, previous }: { current: number; previous?: number }) {
  if (!previous) return <span />;
  const pct = ((current - previous) / previous) * 100;
  const up = pct >= 0;
  // Spending going up is not "good": red for increases, green for decreases.
  return (
    <span className={`font-semibold ${up ? "text-error" : "text-success"}`}>
      {up ? "↑" : "↓"} {Math.abs(pct).toLocaleString("es-AR", { maximumFractionDigits: 1 })}%
    </span>
  );
}

export default function Inicio() {
  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api<Period[]>("/periods") });
  const rubros = useQuery({ queryKey: ["rubros"], queryFn: () => api<Rubro[]>("/rubros") });

  if (periods.isLoading) return <Loading />;
  if (periods.error) return <ErrorBox error={periods.error} />;
  const [latest, previous] = periods.data ?? [];
  const latestTotal = latest ? (latest.total ?? latest.lines_total) : 0;

  return (
    <>
      <PageHeader title="Inicio" subtitle={`Hoy es ${formatDate(new Date())}`} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          icon={<Wallet size={18} />}
          label="Gasto del último mes"
          value={latest ? formatMoneyRound(latestTotal) : "—"}
          footer={
            <>
              <Delta current={latestTotal} previous={previous ? (previous.total ?? previous.lines_total) : undefined} />
              <span>{previous ? "vs mes anterior" : ""}</span>
            </>
          }
        />
        <KpiTile icon={<CalendarDays size={18} />} label="Último período" value={latest ? formatPeriod(latest.id) : "—"} footer={<span>{periods.data?.length ?? 0} liquidaciones cargadas</span>} />
        <KpiTile icon={<ListChecks size={18} />} label="Líneas de gasto" value={latest?.lines ?? 0} footer={<span>en el último período</span>} />
        <KpiTile icon={<BookOpen size={18} />} label="Rubros" value={rubros.data?.length ?? "—"} footer={<span>en todos los períodos</span>} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Liquidaciones" actions={<Link className={buttonClass()} to="/gastos"><Receipt size={16} />Ver gastos</Link>} bodyClassName="p-0 pt-2">
          {periods.data?.length ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-6 py-2">Período</th>
                  <th className="px-6 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {periods.data.slice(0, 12).map((p) => (
                  <tr key={p.id}>
                    <td className="px-6 py-3 font-medium text-gray-900">
                      <Link className="hover:text-primary" to={`/gastos?period=${p.id}`}>{formatPeriod(p.id)}</Link>
                    </td>
                    <td className="tabular px-6 py-3 text-right">{formatMoney(p.total ?? p.lines_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="p-4 text-sm">Todavía no hay liquidaciones publicadas.</p>
          )}
        </Card>
        <Card title="Reglamento de copropiedad">
          <p>Leé el reglamento artículo por artículo y abrí la página original escaneada de cada uno.</p>
          <Link className={`${buttonClass("primary")} mt-4`} to="/reglamento">
            <BookOpen size={16} /> Ir al reglamento
          </Link>
          <p className="mt-6 text-xs text-gray-400">
            Los datos marcados como “Sin verificar” fueron extraídos automáticamente y todavía no los revisó la comisión.
          </p>
        </Card>
      </div>
    </>
  );
}
