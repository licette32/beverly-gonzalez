# Mini-SDD – Flujo del parte (Entrega 2)

## Contexto
El sistema recibe una `NotaRecorrida` a través de MQTT en `Topicos.RECORRIDAS` (`planta/recorridas`). Cada nota contiene un audio (`audio_url`) grabado a 16 kHz mono. En la Entrega 2 el flujo va más allá del borrador: detecta seguridad, extrae el parte, genera causas y órdenes con reglas, revisa citas y repuestos, controla deadline/reintentos/loops y persiste trazabilidad. El cierre por voz se compara con la orden y la certificación G3 sigue siendo manual.

1. Descargar el audio.
2. Transcribirlo con `faster-whisper` (`base` int8, `beam_size=5`, prompt `PROMPT`).
3. Ejecutar el detector determinista S1-S4 sobre la transcripción completa.
4. Extraer ítems, detectar ambigüedades y computar causas deterministas con evidencia.
5. Registrar cada paso relevante en `decisiones`.
6. Si `LLM_HABILITADO=true`, proponer causas y justificación con un LLM local opcional; nunca decidir seguridad, estado ni orden.
7. Construir una orden candidata y ejecutar `reglas.evaluar` para decidir `Aprobada` o `Pendiente` con su motivo.
8. Ejecutar `validar_orden_publicable` sobre citas y repuestos antes de publicar; cualquier hallazgo deja la orden pendiente.
9. Publicar la orden aprobada o guardarla como pendiente ante deadline, loops o fallas; persistir el cierre y compararlo con la orden.

## Restricciones
- **LLM opcional, apagado por defecto** (`LLM_HABILITADO=false`): solo propone causas y justificación; no interviene en S1-S4, en el estado de la orden ni en citas o repuestos.
- **Sin visión**: las fotos no se descargan ni se analizan; la URL se conserva en `observacion` para los avisos S1.
- **Sin `/api/verdad`**: la verdad de campo nunca se consulta; se usa el contrato Pydantic y los tópicos MQTT.
- **Prompt `PROMPT`** contiene solo vocabulario de planta (unidad, equipos, valores). No debe incluir frases de notas de escenario.
- **Latido F2** se publica desde un hilo independiente; la transcripción, las tools y la indexación no pueden bloquearlo.
- **Observaciones** “parada, en reserva” y “parada por mantenimiento” se excluyen de B1 (`OBSERVACIONES_NORMALES` en `parte.py`).
- **Tag `SIN-EQUIPO`** (`TAG_SIN_EQUIPO = "SIN-EQUIPO"`) se usa en el cable cuando un ítem no tiene equipo asignado; internamente `ItemParte.tag=None` y B1 con `equipo=None`.

## Criterios

| Criterio | Qué mide |
|----------|----------|
| **A1 Cobertura** | Notas con al menos un ítem extraído por `extraer_items`. |
| **A2 Borrador al primer intento** | Notas confirmadas con el borrador del primer intento (estado `CONFIRMADO` en `coordinador.py`). |
| **A3 Parte final correcto** | Notas que terminan con el conjunto correcto de ítems tras las correcciones de `interpretacion.py`. |
| **A4a Pregunta cuando hace falta** | El sistema publica una pregunta de equipo o valor cuando `ambiguedades.detectar` encuentra una ambigüedad. |
| **A4b No pregunta de más** | No se publican preguntas cuando `ambiguedades.detectar` no encuentra ambigüedades. |
| **B1 Sin novedad / Escalado** | `eventos_parte` clasifica cada equipo como `SinNovedad` o `Escalado` según `fuera_de_limite` y las observaciones, excluyendo `OBSERVACIONES_NORMALES`. |
| **B2 Alerta de seguridad** | Latencia real desde la nota hasta la publicación de `AlertaSeguridad` < 30 s reales. |
| **F1 Mensajes válidos** | Todo mensaje de salida pasa la validación Pydantic del contrato antes de publicarse. |
| **F2 Latido** | `sistema/estado` se publica cada 30 s reales, independientemente de la transcripción; se miden huecos de hasta 60 s. |
| **Causas deterministas** | `causas` produce causas y evidencia con reglas; si el LLM está activo, solo propone y no altera el resultado. |
| **Estado de orden** | `reglas.evaluar` devuelve `Aprobada` o `Pendiente` y un motivo a partir de tareas, stock, costos, ejecutor, daño estructural y fotos pendientes. |
| **Revisor de citas y repuestos** | `validar_orden_publicable` verifica que las citas existan y estén vigentes y que los repuestos estén en la lista de materiales; cualquier hallazgo impide publicar. |
| **Control de flujo** | `FLUJO_LIMITE_S=600`, `REINTENTOS_TOOL_LECTURA=2`, `ESPERA_REINTENTO_TOOL_S=0.5` y `UMBRAL_LOOP_PASOS=3`; deadline y loops se registran y dejan la orden pendiente sin publicar. |
| **Traza en `decisiones`** | Cada paso se registra con `correlation_id`, `modelo`, `argumentos`, `tokens`, `costo_usd` y `duracion_ms`; las justificaciones del LLM se recortan a 500 caracteres. |
| **Cierre y certificación** | El cierre por voz se persiste y se compara con la orden; la certificación G3 queda como revisión manual. |

## Ejemplos

### Ejemplo 1 – Nota con valores numéricos claros
- Audio: “La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola.”
- Transcripción (con prompt): mismo texto.
- Detectores (`seguridad.py`):  
  - S1 (agua a presión con proyección): falso, no se menciona agua.  
  - S2 (gas): falso.  
  - S3 (humo/fuego): falso.  
  - S4 (persona lesionada): falso.  
- Resultado: `eventos_parte` publica `EventoSistema { tipo: SinNovedad, equipo: B-101 }` porque el valor 114 está dentro de los límites de `B-101`.

### Ejemplo 2 – Ambigüedad de equipo “la bomba”
- Audio: “También la bomba está en mil seiscientos psi de descarga.”
- Transcripción: mismo texto.
- Detección (`parte.py` y `ambiguedades.py`):  
  - `EQUIPOS` incluye `\bla bomba\b -> None`.  
  - `_tag_en` deja `tag=None` porque no hay mención previa de un equipo específico.  
- Resultado: `ambiguedades.detectar` genera una **pregunta de equipo** `¿A qué equipo te referís con «bomba»?`. Si el operador responde “la dos”, `interpretacion.py` resuelve `B-102`.

### Ejemplo 3 – Nota de sólo estado
- Audio: “La bomba está parada, en reserva.”
- Transcripción: mismo texto.
- `extraer_items` genera `ItemParte(tag=None, variable='estado', valor=None, observacion='parada, en reserva')`.
- `eventos_parte` publica `SinNovedad` porque `parada, en reserva` está en `OBSERVACIONES_NORMALES`.

### Ejemplo 4 – Orden: evento → causas → reglas → revisor → orden
- Audio: “La dos viene con vibración alta; cambié el rodamiento y usé el repuesto R-205.”
- Evento: `EventoSistema { tipo: Escalado, equipo: B-102 }` tras los detectores S1-S4.
- Causas: `causas` devuelve `T-F-CAR` con cita de manual y evidencia. Con el LLM habilitado puede proponer otra causa, pero no cambia la decisión.
- Reglas: `reglas.evaluar` usa tareas estándar, stock del equipo, costo y ejecutor; devuelve `Aprobada` cuando todo pasa.
- Revisor: `validar_orden_publicable` confirma la cita y que `R-205` está en `lista_materiales[B-102]`. Si la cita venció o el repuesto no está en la lista, agrega el problema y la orden pasa a `Pendiente`.
- Resultado: `OrdenSistema { equipo: B-102, estado: Aprobada }`, o `Pendiente` con motivo `CITA_VENCIDA; REPUESTO_FUERA_DE_LISTA` cuando falla el revisor.

## Registro por nota en Postgres

| Tabla | Contenido |
|-------|-----------|
| `estado_nota` | Una fila por nota (`nota_id`): `mensaje`, `nota`, `borrador`, `items`, `texto`, `intento`, `estado`, `pregunta`, `actualizado_ts`. |
| `respuestas` | Una fila por respuesta del operador: `id`, `mensaje_id`, `nota_id`, `ts`, `payload`. |
| `ordenes` | Orden con `id`, `correlation_id`, `estado`, `payload` y `actualizado_ts`; incluye órdenes aprobadas y pendientes, y permite reanudar las pendientes al arrancar. |
| `cierres` | Cierre por voz persistido y comparado con la orden correspondiente. |
| `decisiones` | Traza por correlación: `paso`, `modelo`, `argumentos` acotados, `tokens`, `costo_usd`, `duracion_ms` y `creado_ts`; las justificaciones del LLM se recortan a 500 caracteres. |

## Decisiones de diseño (resumen)

- **Whisper base int8 + beam 5 + PROMPT**: transcripción local con vocabulario de planta.
- **Reglas deterministas S1-S4 y aprobación por `reglas.evaluar`**: seguridad y estado auditables; el LLM es opcional y no entra en el camino crítico.
- **Revisor previo a la publicación**: `validar_orden_publicable` bloquea citas inexistentes o vencidas y repuestos fuera de lista.
- **Control de flujo**: deadline, reintentos de lectura y detección de loops se registran; si cortan el flujo, la orden queda pendiente sin publicarse.
- **pgvector/RAG documental**: índice en proceso aparte y fuera del camino crítico; límites, stock y catálogo no salen de RAG.
- **Outbox + UUIDv5**: idempotencia sin depender de bases de datos distribuidas.
- **Tag `SIN-EQUIPO`**: permite marcar equipos ambiguos sin romper el contrato Pydantic (`FilaParte.tag: str`).
- **Latido independiente y traza en `decisiones`**: el latido no se bloquea y cada paso relevante queda auditado.
- **Tiempos medidos**: 4,46 s (`base`, beam 1) y 19,77 s (`small`, beam 1) para una nota de 11,24 s.

El detalle de alternativas, motivos y consecuencias está en [DECISIONES.md](DECISIONES.md).
