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

## Dónde

Postgres 16 con pgvector, en el servicio `postgres` del compose, con el volumen `pgdata`. Los ids de mensajes y eventos son UUIDv5 deterministas, así que repetir una publicación no crea duplicados.

## Si Postgres no responde

El agente sigue trabajando con el estado en memoria. Las escrituras que no se pudieron completar quedan pendientes y se reintentan (ver `_sincronizar_pendientes` en `repositorio.py`; el intervalo es `POSTGRES_REINTENTO_S`). El latido de `sistema/estado` informa la cantidad en `pendientes_sincronizar`. Los pendientes viven en memoria, no en una tabla.

## Qué no se guarda

- El audio: se descarga a un archivo temporal y se borra al terminar la transcripción.
- Las fotos de las notas.
- La verdad ni la corrección de la planta: el agente no las lee en ejecución (D14).

## Cuánto tiempo

En la Entrega 1 no hay expiración automática: el estado persiste mientras exista el volumen `pgdata`. Borrar el volumen reinicia la memoria.

## Qué recuerda entre mensajes de una misma nota

Las correcciones del operador se aplican sobre el borrador guardado (`items`, `intento`), de modo que cada confirmación o corrección parte del estado anterior y no de cero.

## Privacidad

Las transcripciones contienen lo que dijo el operario. Todo el procesamiento y el almacenamiento es local; no se envía nada a servicios externos.
