# Política de memoria

Qué recuerda el agente, dónde, por cuánto tiempo y qué no guarda.

## Qué se guarda por nota

Tabla `estado_nota` (Postgres, una fila por nota, clave `nota_id`):

| Campo | Contenido |
|---|---|
| `mensaje` | último mensaje publicado a la tablet |
| `nota` | la `NotaRecorrida` original (ids, ts, audio_url) |
| `borrador` | filas del parte que ve el operador |
| `items` | ítems extraídos (tag, variable, valor, unidad, observación) |
| `texto` | transcripción de la nota |
| `intento` | cantidad de correcciones aplicadas |
| `estado` | etapa del flujo de la nota |
| `pregunta` | pregunta de desambiguación pendiente, si la hay |
| `actualizado_ts` | última actualización |

Tabla `respuestas` (una fila por respuesta del operador): `id`, `mensaje_id`, `nota_id`, `ts`, `payload`.

La conversación de una nota se recuerda como ese estado, no como una historia libre: cada corrección se aplica sobre `items` e `intento`, y la pregunta pendiente se conserva hasta que llega la respuesta o vence `PREGUNTA_TIMEOUT_S`. No hay resumen generado por LLM ni memoria vectorial por conversación.

## Órdenes, cierres y decisiones

| Tabla | Contenido |
|---|---|
| `ordenes` | orden con `id`, `correlation_id`, `estado`, `payload` y `actualizado_ts`; `cargar_pendientes()` devuelve `pendiente` y `borrador` |
| `cierres` | cierre por voz persistido y comparado con la orden |
| `decisiones` | traza de pasos con `correlation_id = evento.id`, columnas y retención detalladas en [`DECISIONES.md`](DECISIONES.md) |

### Checkpoint de órdenes pendientes

Al arrancar, `CoordinadorPartes.reanudar_pendientes()` consulta `cargar_pendientes()`. Las órdenes `Pendiente` se vuelven a publicar con `publicar_orden`; las `Borrador` solo se loguean, porque todavía no fueron evaluadas por `reglas.evaluar`. El deduplicador usa `ordenes_abiertas(equipo)` y el id determinista de la orden, así que recuperar pendientes no crea duplicados.

Cuando se alcanza el deadline después de construir la orden, `WorkerOrdenes` ya guarda esa orden como **Pendiente** con `LIMITE_TIEMPO` en el motivo y avisa a la tablet, pero **no la publica** en `Topicos.ORDENES`. Queda disponible para el planificador/reanudación. Si el deadline se alcanza antes de construir, no hay orden que guardar.

## Dónde

Postgres 16 con pgvector, en el servicio `postgres` del compose, con el volumen `pgdata`. Los ids de mensajes, eventos y órdenes son UUIDv5 deterministas, así que repetir una publicación no crea duplicados.

## Si Postgres no responde

El agente sigue trabajando con el estado en memoria. Las escrituras que no se pudieron completar quedan pendientes y se reintentan (ver `_sincronizar_pendientes` en `repositorio.py`; el intervalo es `POSTGRES_REINTENTO_S`). El latido de `sistema/estado` informa la cantidad en `pendientes_sincronizar` y el estado del enlace. Los pendientes viven en memoria, no en una tabla.

Cuando el enlace externo está caído y el LLM está habilitado con host externo, el análisis no se llama: `llm.py` agrega `analisis:<correlation_id>` a `ColaPendientes`. Al volver el enlace, esa entrada solo se cuenta como pendiente en el latido; no se reejecuta el análisis.

## Qué no se guarda

- El audio: se descarga a un archivo temporal y se borra al terminar la transcripción.
- Las fotos de las notas: no se descargan ni se asocian a una fila; no hay modelo de visión. La URL de la foto se incluye en `observacion` para el aviso S1.
- La verdad ni la corrección de la planta: el agente no las lee en ejecución (D14).
- Textos libres de búsqueda de manuales ni nombres/motivos de decisiones humanas: se guardan longitudes y hashes acotados. Las justificaciones del LLM se recortan a 500 caracteres.

## Cuánto tiempo

No hay expiración automática: el estado de la nota, las órdenes, los cierres y las decisiones persisten mientras exista el volumen `pgdata`. Borrar el volumen reinicia la memoria. `RegistroDecisionesMemoria` y `ColaPendientes` son variantes en memoria que viven solo durante el proceso.

## Privacidad

Las transcripciones contienen lo que dijo el operario. Todo el procesamiento y el almacenamiento crítico es local; no se envía nada a servicios externos. El LLM es opcional, suele apuntar a un Ollama local y, cuando se usa un host externo, respeta el proxy de planta y `NO_PROXY` para el host local.
