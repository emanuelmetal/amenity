import { useQuery } from "@tanstack/react-query";
import { FileCheck2, FileWarning, Landmark, Receipt, Wallet } from "lucide-react";
import { Link } from "react-router";
import { IncomeVsSpendChart, SpendByRubroChart, TopVendors } from "../components/charts";
import { buttonClass, Card, ErrorBox, KpiTile, Loading, PageHeader } from "../components/ui";
import { api, type MonthlyStat, type RubroStat, type VendorStat } from "../lib/api";
import { formatDate, formatMoneyRound, formatPeriod } from "../lib/format";

function Delta({ current, previous }: { current: number; previous?: number }) {
  if (!previous) return <span />;
  const pct = ((current - previous) / previous) * 100;
  const up = pct >= 0;
  // Spending going up is not "good": red for increases, green for decreases. The arrow carries it too.
  return (
    <span className={`font-semibold ${up ? "text-error" : "text-success"}`}>
      {up ? "↑" : "↓"} {Math.abs(pct).toLocaleString("es-AR", { maximumFractionDigits: 1 })}%
    </span>
  );
}

export default function Inicio() {
  const monthly = useQuery({ queryKey: ["stats", "monthly"], queryFn: () => api<MonthlyStat[]>("/stats/monthly") });
  const rubros = useQuery({ queryKey: ["stats", "rubros"], queryFn: () => api<RubroStat[]>("/stats/rubros") });
  const vendors = useQuery({ queryKey: ["stats", "proveedores"], queryFn: () => api<VendorStat[]>("/stats/proveedores") });

  if (monthly.isLoading) return <Loading />;
  if (monthly.error) return <ErrorBox error={monthly.error} />;
  const months = monthly.data ?? [];
  const latest = months.at(-1);
  const previous = months.at(-2);
  // Receipt coverage only means something for months whose receipts were uploaded.
  const withReceipts = months.filter((m) => m.receipts > 0).at(-1);
  const coverage = withReceipts && withReceipts.gastos ? withReceipts.con_comprobante / withReceipts.gastos : null;

  return (
    <>
      <PageHeader title="Inicio" subtitle={`Hoy es ${formatDate(new Date())}`} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          icon={<Wallet size={18} />}
          label={latest ? `Gastos de ${formatPeriod(latest.id)}` : "Gastos del último mes"}
          value={latest ? formatMoneyRound(latest.gastos) : "—"}
          footer={
            <>
              <Delta current={latest?.gastos ?? 0} previous={previous?.gastos} />
              <span>{previous ? "vs mes anterior" : ""}</span>
            </>
          }
        />
        <KpiTile
          icon={<Landmark size={18} />}
          label="Saldo al cierre"
          value={latest?.saldo_final != null ? formatMoneyRound(latest.saldo_final) : "—"}
          footer={<span>{latest?.ingresos != null ? `Ingresos del mes: ${formatMoneyRound(latest.ingresos)}` : ""}</span>}
        />
        <KpiTile
          icon={<FileCheck2 size={18} />}
          label="Gasto con comprobante y pago"
          value={coverage != null ? `${Math.round(coverage * 100)}%` : "—"}
          footer={<span>{withReceipts ? `en ${formatPeriod(withReceipts.id)}` : "Todavía no hay comprobantes cargados"}</span>}
        />
        <KpiTile
          icon={<FileWarning size={18} />}
          label="Gastos sin respaldo completo"
          value={withReceipts ? withReceipts.lineas_sin_comprobante : "—"}
          footer={
            withReceipts ? (
              <Link className="font-medium text-primary hover:underline" to="/analisis?ver=sin-comprobante">
                Ver cuáles
              </Link>
            ) : (
              <span />
            )
          }
        />
      </div>

      <Card title="Ingresos y gastos por mes">
        {months.length ? <IncomeVsSpendChart data={months} /> : <p className="text-sm">Todavía no hay liquidaciones publicadas.</p>}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          title="Gasto por rubro"
          className="lg:col-span-2"
          actions={<Link className={buttonClass()} to="/gastos"><Receipt size={16} />Ver gastos</Link>}
        >
          {rubros.error ? <ErrorBox error={rubros.error} /> : rubros.data ? <SpendByRubroChart stats={rubros.data} /> : <Loading />}
        </Card>
        <Card title="Principales proveedores" actions={<Link className={`${buttonClass()} whitespace-nowrap`} to="/comprobantes">Ver todos</Link>}>
          {vendors.error ? (
            <ErrorBox error={vendors.error} />
          ) : vendors.data?.length ? (
            <TopVendors data={vendors.data} />
          ) : vendors.data ? (
            <p className="text-sm">Todavía no hay comprobantes cargados.</p>
          ) : (
            <Loading />
          )}
        </Card>
      </div>
      <p className="text-xs text-gray-400">
        Los datos marcados como “Sin verificar” fueron extraídos automáticamente y todavía no los revisó la comisión.
      </p>
    </>
  );
}
