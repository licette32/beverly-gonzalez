# Mini-SDD – Flujo del parte (Entrega 1)

## Contexto
El sistema recibe una `NotaRecorrida` a través de MQTT (`sistema/recorridas`). Cada nota contiene un audio (`audio_url`) grabado a 16 kHz mono. El agente debe:
1. Descargar el audio.
2. Transcribirlo con `faster-whisper` (`base` int8, `beam_size=5`, prompt `PROMPT`).
3. Ejecutar el detector determinista S1-S4 sobre la transcripción completa.
4. Publicar un `EventoSistema` (tipo `SinNovedad`/`Escalado`) y, si procede, un `MensajeTablet` con un borrador de parte.

## Restricciones
- **Sin LLM**: la alarma (B2) se decide con reglas deterministas sobre valores numéricos y observaciones.
- **Sin `/api/verdad`**: la verdad de campo nunca se consulta; se usa el contrato Pydantic y los MQTT topics.
- **Prompt `PROMPT`** contiene solo vocabulario de planta (unidad, equipos, valores). No debe incluir frases de notas de escenario.
- **Latido F2** se publica desde un hilo independiente; la transcripción y la descarga nunca pueden bloquearlo.
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

## Registro por nota en Postgres

| Tabla | Contenido |
|-------|-----------|
| `estado_nota` | Una fila por nota (`nota_id`): `mensaje`, `nota`, `borrador`, `items`, `texto`, `intento`, `estado`, `pregunta`, `actualizado_ts`. |
| `respuestas` | Una fila por respuesta del operador: `id`, `mensaje_id`, `nota_id`, `ts`, `payload`. |

## Decisiones de diseño (resumen)

- **Whisper base int8 + beam 5 + PROMPT**: transcripción local con vocabulario de planta.
- **Reglas deterministas S1-S4**: detección de seguridad sin LLM; B2 exige que la alerta salga en < 30 s reales.
- **Tiempos medidos**: 4,46 s (`base`, beam 1) y 19,77 s (`small`, beam 1) para una nota de 11,24 s.
- **Outbox + UUIDv5**: idempotencia sin depender de bases de datos distribuidas.
- **Tag `SIN-EQUIPO`**: permite marcar equipos ambiguos sin romper el contrato Pydantic (`FilaParte.tag: str`).
- **Latido independiente**: hilo separado evita que una transcripción lenta bloquee el sistema.
