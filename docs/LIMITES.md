# Límites de control

El agente de la Entrega 1 no usa un modelo de lenguaje en el camino crítico, así
que no hay tokens ni costo que limitar. Lo que se limita es el tiempo y las
rondas. Al llegar a un límite el agente avisa a la tablet y se detiene.

| Etapa | Límite | Variable | Qué pasa al llegar |
|---|---|---|---|
| Descarga del audio | 60 s por intento, 3 intentos | `AUDIO_TIMEOUT_S`, `AUDIO_INTENTOS` | Aviso a la tablet; la nota no se procesa |
| Transcripción | 90 s por nota | `TRANSCRIPCION_LIMITE_S` | Aviso a la tablet; la nota no se procesa |
| Pregunta de desambiguación | 60 s sin respuesta | `PREGUNTA_TIMEOUT_S` | Se publica el borrador con lo disponible y el evento B1 con lo que hay; lo no confirmado queda marcado en la observación |
| Correcciones por nota | 5 rondas | `MAX_CORRECCIONES` | Aviso a la tablet; el parte queda como está y todavía se puede confirmar |
| Base de datos | Reintento cada `POSTGRES_REINTENTO_S` | `POSTGRES_REINTENTO_S` | No bloquea el camino crítico; las escrituras quedan pendientes en memoria y el latido las informa |
| Herramientas HTTP de solo lectura | 5 s por intento, 2 intentos, 0,5 s entre intentos | `HISTORIAN_TIMEOUT_S`, `CATALOGO_TIMEOUT_S`, `HISTORIAL_TIMEOUT_S`, `REINTENTOS_TOOL_LECTURA`, `ESPERA_REINTENTO_TOOL_S` | Timeout/conexión/5xx se reintentan; 4xx y errores de parseo no; cada intento se registra en `decisiones` |
| Flujo de una orden | 600 s por orden | `FLUJO_LIMITE_S` | Antes de construir: `orden=None` y `LIMITE_TIEMPO`; después: orden pendiente guardada con `LIMITE_TIEMPO`, sin publicar en `Topicos.ORDENES` |
| Repetición de pasos | 3 repeticiones de `(paso, herramienta, argumentos)` por `correlation_id` | `UMBRAL_LOOP_PASOS` | Se registra `paso="loop"`; la orden queda pendiente con `LOOP_DETECTADO` |

## Reglas

- Al cortar nunca se publica `SinNovedad` ni otro evento de planta: solo un
  aviso a la tablet (`espera_respuesta=False`).
- La detección de seguridad corre sobre el texto transcripto. Si la transcripción
  no termina no hay texto que analizar; en ese caso el aviso pide revisar la
  nota a mano. Es una limitación conocida.
- Los avisos de corte tienen un id determinista por motivo y nota, así que
  repetirlos no genera duplicados.
- La orden pendiente por deadline se guarda en `ordenes` para que el planificador
  la retome; no se publica en `Topicos.ORDENES` ni se reprocesa.
- El deadline del flujo y la detección de loops son cooperativos: se verifican
  entre etapas, sin hilos que interrumpan llamadas en vuelo.
- Un loop se decide solo por repetición de `(paso, herramienta, argumentos)`
  dentro del mismo `correlation_id`. No se infiere de transiciones:
  `aprobada → pendiente` no existe y `registrar_cierre` es idempotente.
- `argumentos` distingue las dos lecturas de materiales: una viene de
  `tareas_no_estandar` y otra de `_cargar_materiales`.
- Los errores finales de las herramientas se registran con
  `reintentable=False` para evitar multiplicadores de reintentos.
- Los valores por defecto se pueden cambiar por variable de entorno en el compose.

## Límites de transiciones y CLI

- `Observada` no tiene salientes: no se implementó responder la observación ni
  volver a certificar desde ese estado.
- `certificar` no calcula el monto: la CLI recibe `--habilita` y `--monto`;
  `transicionar` valida el formato `HAB-AAAA-NNNN` y que el monto sea mayor que
  cero, pero no consulta la lista de precios CT-SVP-2025.
- `--por NOMBRE` es obligatorio y se escribe en el log de la CLI. No hay
  autenticación, autorización por rol ni bitácora persistente del operador.
- La CLI no tiene timeout propio: solo consulta el deadline cooperativo antes de
  publicar. No abre un temporizador porque opera una única orden ya cargada y
  una interrupción en medio de la escritura dejaría un estado ambiguo.
- La CLI no reintenta `aprobar`, `rechazar`, `certificar` ni `observar`: son
  escrituras, y un reintento ciego podría duplicar transiciones. Un error se
  informa y se devuelve código 1.
- La idempotencia multi-proceso depende de `estado_esperado`: `publicar_orden`
  usa `guardar_si_estado` con `UPDATE ... WHERE id AND estado`. Sin ese valor no
  hay comparación condicional.

Los comandos están pensados para ejecutarse dentro del contenedor, por
ejemplo:

```text
docker compose exec agente python -m sistema.cli aprobar ORDEN_ID --por NOMBRE
```

## Límites del enganche de órdenes

- El deduplicador consulta `ordenes_abiertas(equipo)`: bloquean `Pendiente`,
  `Aprobada`, `Ejecutada` y `Observada` con el mismo conjunto de tareas;
  `Rechazada`, `Cerrada` y `Certificada` no bloquean. El mapa en memoria es una
  caché: si Postgres vuelve a consultarse y ya no hay orden abierta, se descarta.
- El almacén de anomalías recientes es en memoria, acotado y con lock. No
  sobrevive a un reinicio; el historial persistente es el de órdenes.
- Si falla `/api/estado`, `estado_bombas` queda en `None`: la reserva no está
  confirmada y una tarea que detiene la bomba queda pendiente por
  `REDUCE_INYECCION`. Si falla el historial con timeout o error de herramienta,
  se avisa a la tablet y no se publica la orden; otros fallos se siguen sin
  reordenar causas.
- Una nota con fotos se marca `fotos_pendientes_de_analisis=True` y la orden
  queda pendiente por `FOTOS_PENDIENTES`; no hay análisis de imágenes.
- En `fuga-sin-enlace`, la S1 de B-101 no genera orden. La nota se detecta como
  alerta de seguridad y se publica en `sistema/eventos` como `AlertaSeguridad`,
  pero no se convierte en `Escalado`. La caída de descarga informada (113,6 a
  104,7 kg/cm²) no llega a `alarma_baja=95`, así que los sensores tampoco
  escalan. La fila `condicion_insegura` no coincide con las firmas de `FALLAS` y
  la foto de daño estructural no se analiza: no hay tarea derivable y no se
  inventa ninguna. No aplica `MBP-4 §17.1` porque es una sección de PIA-1.

## Límite del corrector en A2/A3

El corrector oficial no puede confirmar notas cuyo único contenido es una fila de
estado o de seguridad: `planta_sim/dialogo.py` calcula `filas_mostradas` contando
solo filas con `valor != None`, y `confirmo` se setea comparando únicamente los
ítems de la verdad con `valor != None`. Las filas `estado` y `condicion_insegura`
tienen `valor=None` por contrato, así que `SIN-EQUIPO`/`PLANTA`/`B-101` con valor
nulo no cuentan como borrador y no se confirman.

Evidencia reproducible con `dialogo.responder` sobre NOTA-00008:

- `B-103/estado/valor=None` → `filas_mostradas=0`, `problemas=[sin_borrador]`.
- `B-103/estado/valor=0.0` → `filas_mostradas=1`, pero `confirmo=False` por
  `sobra` (“Lo de la tres no lo dije”).

Por eso #23 corrige la presentación (tag y URL de la foto en `observacion`) pero
no puede subir A2/A3 con este corrector. El hallazgo se reporta al curso: para
que estas notas cuenten, el corrector debería aceptar filas con `valor=None`
comparando `tag`, `variable` y `observacion`/`foto`.
