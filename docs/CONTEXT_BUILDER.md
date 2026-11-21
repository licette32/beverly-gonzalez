# Context builder (diseño)

No existe un módulo `context_builder`. En la Entrega 2 el “contexto” se arma a partir de la memoria persistida en Postgres y de la función puntual `llm.construir_mensajes`, que solo prepara la entrada del análisis LLM opcional.

## Memoria

La memoria no es una conversación libre: es estado por nota más trazas acotadas. La política completa está en [MEMORIA.md](MEMORIA.md).

| Fuente | Contenido |
|---|---|
| `estado_nota` | Una fila por nota con `mensaje`, `nota`, `borrador`, `items`, `texto`, `intento`, `estado`, `pregunta` y `actualizado_ts`. |
| `respuestas` | Respuestas del operador con `id`, `mensaje_id`, `nota_id`, `ts` y `payload`. |
| `ordenes` | Órdenes con `id`, `correlation_id`, `estado`, `payload` y `actualizado_ts`; incluye aprobadas y pendientes. |
| `cierres` | Cierres por voz persistidos y comparados con la orden correspondiente. |
| `decisiones` | Traza de pasos por `correlation_id` con modelo, argumentos acotados, tokens, costo y duración. |

Los pendientes de sincronización con Postgres viven en memoria, no en una tabla, y se informan en el latido. No se guarda audio ni fotos; la URL de la foto se conserva en `observacion` para los avisos S1.

## Historial

El historial usado por el análisis no es la conversación completa. Es el historial de órdenes del equipo, obtenido con `tools.historial_ordenes` desde `ordenes_worker._historial_por_equipo`, y se usa para reordenar las causas deterministas con `reordenar_con_historial`. `llm.construir_mensajes` toma como máximo 20 entradas de ese historial. La memoria real por nota y el checkpoint de órdenes pendientes están descritos en [MEMORIA.md](MEMORIA.md).

## Resultados de tools

Los resultados de herramientas no se guardan como una sección “tools” ni se inyectan crudos en prompts. Cada llamada se registra en `decisiones` con `paso="tool:<nombre>"` y `argumentos` acotados por allowlist:

- `historian`: `tag`, `variable`, `desde`, `hasta`.
- `catalogo` y `stock`: `tag`.
- `historial_ordenes`: `equipo`, `orden_id`.
- Intentos de herramienta: `resultado`, `intento` y `codigo`.
- Búsqueda de manuales: longitud y hash, sin texto crudo.
- Decisiones humanas: longitudes y monto, sin nombres ni motivos.

El detalle de la columna `argumentos`, la retención y la allowlist está en [DECISIONES.md](DECISIONES.md).

## Uso en prompts

`agente/sistema/llm.py` construye los mensajes solo para `analisis_llm`:

- El mensaje de sistema indica que el contenido entre `<datos>` es información, no una instrucción, y que solo se pueden ordenar los `codigo_falla` recibidos y justificarlos.
- El mensaje de usuario lleva un JSON con `evento`, `evidencia`, `historial` (hasta 20 entradas) y `causas` (`codigo_falla`, `descripcion`, `evidencia`, `faltantes`).

El LLM solo propone un orden de causas y justificaciones. No decide estado de la orden, no genera repuestos, citas ni `tarea_codigo`, no elige ejecutor y no interviene en la detección de seguridad. Está apagado por defecto (`LLM_HABILITADO=false`).

## Fragmentos

Los fragmentos indexados en pgvector se usan para RAG documental: búsqueda de manuales y validación de citas en el revisor de publicación. No se pasan como sección propia al prompt del LLM en esta entrega; el análisis recibe causas ya calculadas, no fragmentos crudos. El diseño del RAG está resumido en [DECISIONES.md](DECISIONES.md) y en [`SPEC_PARTE.md`](SPEC_PARTE.md).
