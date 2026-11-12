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

## Reglas

- Al cortar nunca se publica `SinNovedad` ni otro evento de planta: solo un
  aviso a la tablet (`espera_respuesta=False`).
- La detección de seguridad corre sobre el texto transcripto. Si la transcripción
  no termina no hay texto que analizar; en ese caso el aviso pide revisar la
  nota a mano. Es una limitación conocida.
- Los avisos de corte tienen un id determinista por motivo y nota, así que
  repetirlos no genera duplicados.
- Los valores por defecto se pueden cambiar por variable de entorno en el compose.
