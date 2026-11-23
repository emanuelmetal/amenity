import { Card, PageHeader } from "../components/ui";

export default function ComoFunciona() {
  return (
    <>
      <PageHeader title="Cómo funciona" subtitle="Qué es este portal, de dónde salen los datos y cómo se protege tu privacidad." />
      <div className="grid max-w-3xl grid-cols-1 gap-4 text-sm leading-6">
        <Card title="¿Qué es?">
          <p>
            Un sitio privado para los vecinos de la Torre 3. Reúne las liquidaciones de expensas, el reglamento de copropiedad, los
            comprobantes, los resúmenes bancarios y las actas de la comisión, para que cualquiera pueda consultarlos, buscar en ellos y
            comentarlos.
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
        <Card title="Actas">
          <p>
            Las actas son fotos del libro manuscrito de la comisión, publicadas tal como están en el libro (por decisión de la comisión,
            con sus firmas). El texto de cada acta está transcripto a mano: en la transcripción las personas aparecen por su rol
            (“una integrante de la comisión”, “el administrador”), no por su nombre. Ante cualquier duda, la foto es lo que vale.
          </p>
        </Card>
        <Card title="Comentarios anónimos">
          <ul className="list-disc space-y-1 pl-5">
            <li>Todos los comentarios se muestran como “Vecino/a anónimo/a”. El sitio no muestra a nadie quién escribió qué.</li>
            <li>
              Cada navegador recibe al entrar un identificador al azar, guardado en su sesión. El sitio guarda una huella cifrada de ese
              identificador (no el identificador en sí) para poder limitar a 10 comentarios por día, dejarte borrar los tuyos y contar una
              sola denuncia por dispositivo. Si entrás de nuevo con el enlace o desde otro navegador, sos otro dispositivo.
            </li>
            <li>
              El sitio también guarda con qué enlace de acceso se escribió cada comentario. Con el enlace compartido de toda la torre eso
              no identifica a nadie. Si algún día se usan enlaces por departamento, quien administra la base de datos podría ver desde qué
              departamento se escribió un comentario: la comisión acordará quién puede mirarlo y cuándo, y se avisará antes del cambio.
            </li>
            <li>
              Con 3 denuncias de dispositivos distintos, un comentario se oculta hasta que lo revise un moderador de la comisión, que puede
              ocultarlo o restaurarlo. Cada decisión de moderación queda registrada.
            </li>
            <li>Ser anónimo en el sitio no quita la responsabilidad legal de cada persona por lo que escribe.</li>
          </ul>
        </Card>
        <Card title="Preguntale al portal">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              Tu pregunta se envía a un modelo de inteligencia artificial de Cloudflare (Workers AI), que la traduce a una consulta sobre
              los datos que ya se ven en el portal. El modelo no ve los datos: solo la pregunta y la lista de columnas disponibles.
            </li>
            <li>
              La consulta solo puede leer gastos, comprobantes, pagos, observaciones, actas y reglamento; nunca comentarios ni datos de
              acceso. Siempre se muestra la consulta usada, para que puedas revisarla.
            </li>
            <li>El portal no guarda tus preguntas; solo cuenta cuántas se hicieron en el día: hasta 20 por dispositivo con el enlace compartido, o por enlace si es un enlace por departamento.</li>
            <li>No escribas datos personales en la pregunta. La respuesta puede tener errores: confirmá los números en Gastos o Análisis.</li>
          </ul>
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
