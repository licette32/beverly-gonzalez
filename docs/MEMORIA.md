# Memoria – qué se guarda por nota, dónde y cuánto tiempo

## Registro por cada `NotaRecorrida`

| Campo | Tabla / Ubicación | Tipo / Formato | Tiempo aproximado |
|-------|-------------------|----------------|-------------------|
| **audio_url** | `audios` (archivo WAV, 16 kHz mono) | Ruta relativa o absoluta al archivo descargado | ↓ 0.5 s (download from plant simulator) |
| **transcripción** | `transcripciones` (texto + metadatos: duración, modelo, beam_size) | `texto` (cadena), `modelo` (`base` int8), `beam_size` (5), `prompt` (aplicado) | 4‑5 s (Whisper base, 16 s de audio) |
| **items_extraídos** | `items` (registro `ItemParte`) | `tag` (str o `None`), `variable` (str), `valor` (float o `None`), `unidad` (str o `None`), `observation` (str o `None`) | < 0.5 s (parser determinista) |
| **evento_sistema** | `eventos_sistema` (PK `id` UUID determinista, `ts_real`, `tipo`, `equipo`, `origen`, `nota_ids`) | `id` (UUIDv5), `tipo` (`SinNovedad`/`Escalado`), `equipo` (str o `None`), `origen` (`"parte"`), `nota_ids` (lista[str]) | < 0.2 s (publicación MQTT QoS 1) |
| **mensaje_tablet** | `mensajes_tablet` (cuando procede: ambigüedad de equipo o valor) | `pantalla` (objeto JSON con `titulo`, `filas`, `opciones`), `texto` (mensaje al operador), `espera_respuesta` (bool) | < 0.2 s |
| **latido** | Publicación `sistema/estado` (cada 30 s reales) | No se almacena por nota; es un hilo independiente que emite `{"sistema":"pia3-agente-planta","enlace_ok":true,"pendientes_sincronizar":0}` cada 30 s | — (hilo de fondo) |

## Tiempo total desde la llegada de la nota

- **Notas cortas** (≤ 10 s de audio): descarga ~0.5 s + transcripción ~4‑5 s + parser < 0.5 s + publicación < 0.2 s ≈ **5‑6 s**.
- **Notas largas** (≈ 16 s de audio, como NOTA‑00011): descarga ~0.5 s + transcripción ~9‑11 s (beam 5 + prompt) + parser < 0.5 s + publicación < 0.2 s ≈ **10‑12 s**.
- **Si la transcripción supera los 20 s** (raro, ocurre con audio corrupto), el sistema espera a que `_listo` se signalice; la nota queda encolada y se procesa cuando el modelo esté listo.

## Almacenamiento físico (PostgreSQL)

- **Schemas/tablas**: `audios`, `transcripciones`, `items`, `eventos_sistema`, `mensajes_tablet`, `pending_sincronizar`.
- **Indices**: PK UUID, índice sobre `equipo` y `tipo` para consultas rápidas de B1.
- **Conexión**: `postgresql://novit:novit@postgres:5432/novit`; se usa `psycopg` 3.x con `autocommit=False` y outbox para reintento.

## Notas de operación

- El **latido** se emite desde un hilo separado; nunca se bloquea por descarga o transcripción. Si el modelo falla al cargarse, el evento `_listo` se fuerza a `True` para desbloquear al worker (la nota se transcribirá con un modelo en frío, se observará una degradación de precisión).
- El **prompt `PROMPT`** se comparte como constante en `agente/sistema/transcripcion.py`; su contenido es solo vocabulario de planta (equipos, unidades, valores). No debe contener fragmentos de notas de escenario.
- Cada nota genera un **UUID determinista** (`UUIDv5(namespace, f"pia3:{nota_id}"`) para su `id` en `eventos_sistema` y `pending_sincronizar`, lo que garantiza idempotencia aun después de reinicios.