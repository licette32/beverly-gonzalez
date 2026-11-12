# Mini‑SDD – Flujo del parte (Entrega 1)

## Contexto
El sistema recibe una `NotaRecorrida` a través de MQTT (`sistema/recorridas`). Cada nota contiene un audio (`audio_url`) de 10‑20 s grabado a 16 kHz mono. El agente debe:
1. Descargar el audio.
2. Transcribirlo con `faster‑whisper` (`base` int8, `beam_size=5`, prompt `PROMPT`).
3. Ejecutar el detector determinista S1‑S4 sobre la transcripción completa.
4. Publicar un `EventoSistema` (tipo `SinNovedad`/`Escalado`) y, si procede, un `MensajeTablet` con un borrador de parte.

## Restricciones
- **Sin LLM en el camino crítico**: la alarma (B2) se decide con reglas sobre valores numéricos y observaciones; el modelo sólo estructuriza datos.
- **Sin `/api/verdad`**: la verdad de campo nunca se consulta; se usa el contrato Pydantic y los MQTT topics.
- **Prompt `PROMPT`** contiene solo vocabulario de planta (unidad, equipos, valores). No debe incluir frases de notas de escenario.
- **Latido F2** se publica desde un hilo independiente; la transcripción, descarga y LLM nunca pueden bloquearlo.
- **Observaciones** “parada, en reserva” y “parada por mantenimiento” se excluyen de B1.
- **Tag `SIN‑EQUIPO`** (`TAG_SIN_EQUIPO = "SIN‑EQUIPO"`) se usa en wire cuándo un item no tiene equipo asignado; internamente `ItemParte.tag=None` y B1 con `equipo=None`.

## Criterios de aceptación (por defecto)

| Criterio | Umbral | Comentario |
|----------|--------|------------|
| **A1 Cobertura** | ≥ 90 % de las notas deben tener al menos un item extraído. | Se mide sobre las 20 verdades del escenario. |
| **A2 Borrador al primer intento** | ≥ 50 % de las notas deben confirmarse con el primer borrador. | El operador virtual sólo confirma si todas las filas numéricas coinciden. |
| **A3 Parte final correcto** | ≥ 60 % de las notas deben terminar con el conjunto correcto de items. | Incluye correcciones de equipo y valor. |
| **A4a Pregunta cuando hace falta** | El sistema debe publicar una pregunta de equipo/valor cuando la detección es ambigua. | Se mide si la pregunta se publica y si el operador responde. |
| **A4b No pregunta de más** | El sistema no debe publicar preguntas cuando todos los items ya están definidos. | Se mide la ausencia de preguntas innecesarias. |
| **B1 Sin novedad / Escalado** | Clasificación correcta de cada equipo según `presion_descarga_local` y `presion_diferencial` vs límites. | Se excluyen observaciones “parada, en reserva”. |
| **B2 Alerta de seguridad** | Latencia real desde la nota hasta la publicación de `AlertaSeguridad` < 30 s reales (medido con `beam_size=5`). | Se mide la diferencia `ts_real(AlertaSeguridad) – ts_real(Nota)`. |
| **F1 Mensajes válidos** | 100 % de los mensajes de salida deben pasar validación Pydantic antes de publicarse. | |
| **F2 Latido** | El latido `sistema/estado` debe publicarse cada 30 s reales, independientemente de la transcripción. | Se mide el hueco entre latidos. |
| **E1 Sigue andando sin enlace** | El sistema debe seguir operativo aunque se pierda la conexión con el broker externo. | |
| **E2 Pendientes visibles** | Las pending deben aparecer en la cola y ser procesadas tras reconexión. | |
| **E3 Sin duplicados** | El outbox y los UUID deterministas deben evitar la re‑publicación de eventos u órdenes. | |

## Ejemplos

### Ejemplo 1 – Nota con valores numéricos claros
- Audio: “La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola.”
- Transcripción (con prompt): mismo texto.
- Detectores:  
  - S1 (presión alta): falso (114 kg < 125 kg).  
  - S2 (olor a gas): falso.  
  - S3 (humo): falso.  
  - S4 (persona lesionada): falso.  
- Resultado: `EventoSistema { tipo: SinNovedad, equipo: B‑101 }`.

### Ejemplo 2 – Ambiguedad de equipo “la bomba”
- Audio: “También la bomba está en mil seiscientos psi de descarga.”
- Transcripción: mismo texto.
- Detectores:  
  - `EQUIPOS` incluye `\bla bomba\b -> None`.  
  - `_tag_en` elige `None` porque no hay mención precedente de equipo específico.  
- Resultado: se publica una **pregunta de equipo** `¿A qué equipo te referís con «bomba»?`. El operador responde “la dos”, y el borrador queda con `B‑102`.

### Ejemplo 3 – Nota de sólo estado
- Audio: “La bomba está parada, en reserva.”
- Transcripción: mismo texto.
- Detectores:  
  - Se extrae `ItemParte(tag=None, variable='estado', valor=None, observación='parada, en reserva')`.  
  - B1 se clasifica como `SinNovedad` (la observación está en la lista de exclusión).  
- A2/A3: la nota **no cuenta** para confirmación de borrador (limitación del operador virtual).

## Registro por nota (Memoria)

| Campo | Dónde se guarda | Tiempo aproximado |
|-------|----------------|-------------------|
| `audio_url` | Tabla `audios` (archivo WAV 16 kHz mono) | ↓ 0.5 s (download) |
| `transcripción` | Tabla `transcripciones` (texto + metadatos) | 4‑5 s con `beam_size=5` + prompt |
| `items_extraídos` | Tabla `items` (ItemParte) | < 0.5 s (parser) |
| `evento_sistema` | Tabla `eventos_sistema` (PK por UUID determinista) | < 0.2 s (publicación MQTT) |
| `mensaje_tablet` | Tabla `mensajes_tablet` (cuando procede) | < 0.2 s |
| `latido` | Publicación `sistema/estado` cada 30 s reales | — |

El tiempo total desde la llegada de la nota hasta tener el evento y el borrador suele estar en el orden de **8‑12 s** para notas cortas (≤ 10 s de audio) y hasta **20‑25 s** para notas largas (≈ 16 s de audio) cuando la transcripción domina el tiempo.

## Decisiones de diseño (resumen)

- **Whisper base int8 + beam 5 + PROMPT**: equilibrio entre velocidad (≈ 4‑5 s por nota) y precisión de números y nombres de equipos.  
- **Reglas deterministas S1‑S4**: garantizan latencia predecible y cumplimiento de B2.  
- **Outbox + UUIDv5**: idempotencia sin depender de bases de datos distribuidas.  
- **Tag `SIN‑EQUIPO`**: permite marcar equipos ambiguos sin romper el contrato Pydantic (`FilaParte.tag: str`).  
- **Latido independiente**: hilo separado evita que una transcripción lenta bloquee el sistema.