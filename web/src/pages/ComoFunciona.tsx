import { Card, PageHeader } from "../components/ui";

export default function ComoFunciona() {
  return (
    <>
      <PageHeader title="Cómo funciona" subtitle="Qué es este portal, de dónde salen los datos y cómo se protege tu privacidad." />
      <div className="grid max-w-3xl grid-cols-1 gap-4 text-sm leading-6">
        <Card title="¿Qué es?">
          <p>
            Un sitio privado para los vecinos de la Torre 3. Reúne las liquidaciones de expensas, el reglamento de copropiedad y, más
            adelante, los comprobantes y las actas de la comisión, para que cualquiera pueda consultarlos y buscar en ellos.
          </p>
        </Card>
        <Card title="¿De dónde salen los datos?">
          <p>
            De los PDF y escaneos que envía la administración. Un proceso automático lee cada página y separa las líneas de gasto y los
            artículos. Como la lectura automática puede equivocarse, cada dato tiene un estado: <strong>Verificado</strong> si lo revisó una
            persona de la comisión, o <strong>Sin verificar</strong> si todavía no. Ante cualquier duda, siempre podés abrir la página original.
          </p>
        </Card>
        <Card title="¿Cómo se entra?">
          <p>
            Con un enlace de acceso que comparte la comisión. Al abrirlo, tu navegador guarda una sesión por 180 días. El enlace puede
            cambiarse en cualquier momento (por ejemplo, si se difunde fuera del edificio); en ese caso hay que pedir el nuevo.
          </p>
          <p className="mt-2">No compartas el enlace fuera de los vecinos de la torre.</p>
        </Card>
        <Card title="Privacidad">
          <ul className="list-disc space-y-1 pl-5">
            <li>El sitio no aparece en buscadores y los archivos solo se descargan con una sesión válida.</li>
            <li>No se publican los recibos de sueldo del encargado ni datos bancarios; los CUIL, DNI y CBU se ocultan en el texto.</li>
            <li>No se publican deudas por unidad salvo decisión de la comisión o la asamblea.</li>
            <li>No guardamos tu nombre, correo ni teléfono.</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
