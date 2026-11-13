# Entrega 1 – Parte por voz y detección en planta

## Cómo levantar el sistema

1. **Levantar la planta**  
   La planta (`broker`, `enlace`, `sim`, `visor`) viene del compose del curso; este repositorio solo define `agente` y `postgres` en `docker-compose.yml`.
   ```bash
   docker compose -p planta -f [COMPLETAR: compose de la planta del curso] up -d broker enlace sim visor
   ```
   Esto inicia el broker MQTT, el simulador de planta, el visor y el servicio de enlace.

2. **Levantar el agente del cursante**  
   ```bash
   docker compose -p alumno-novit -f docker-compose.yml up -d
   ```
   El agente se conecta al broker `planta-lan` y publica `sistema/estado` cada 30 s (latido F2).  
   - Build: `docker compose build`.  
   - Variables de entorno (en `.env` o `docker compose`): `MQTT_HOST`, `POSTGRES_DSN`, `PREGUNTA_TIMEOUT_S=60`, `OMP_NUM_THREADS=2`.

3. **Base de datos**  
   PostgreSQL 16 con extensión `pgvector` (imagen `pgvector/pgvector:pg16`).  
   - DSN: `postgresql://novit:novit@postgres:5432/novit`.  
   - El sistema persiste `estado_nota` y `respuestas`, y reintenta las escrituras pendientes.

4. **Correr la corrección**  
   ```bash
   python correccion/corregir.py --repo . --alumno <nombre> --escenarios martes-tranquilo fuga-sin-enlace --salida correccion/corridas/<nombre>
   ```
   - `--sin-construir` evita reconstruir la planta y el sistema; sin él se hace un `docker compose build --no-cache`.  
   - Los resultados (`.json`, `.md`) se guardan en la carpeta indicada.

## Estructura del repositorio

En la raíz del repositorio público en GitHub deben estar:
- `README.md` – cómo levantar y probar el sistema
- `docker-compose.yml` – definición de servicios
- `tests/` – suite de tests automatizados

## Servicios y decisiones clave (resumen)

| Servicio | Rol | Decisión importante |
|----------|-----|---------------------|
| **agente** | Recibe mensajes MQTT, descarga audio, transcribe con Whisper base int8 (beam 5 + `PROMPT`), ejecuta detectores S1-S4, publica `EventoSistema` y `MensajeTablet`. | Usa reglas deterministas; no hay LLM en la Entrega 1. |
| **postgres** | Persiste `estado_nota` y `respuestas`; reintenta las escrituras pendientes. | `pgvector/pgvector:pg16`; sin dependencia de Redis. |

La planta (`broker`, `enlace`, `sim`, `visor`) es un servicio del curso, fuera de este compose.

## Qué corre en la planta y qué en la nube

Todo corre en la PC de planta: transcripción con `faster-whisper` `base` int8, detección S1-S4, reglas deterministas y Postgres. No hay componentes en la nube en la Entrega 1. La justificación está en `docs/DECISIONES.md` D1: no hay GPU, se usan 4 núcleos y 8 GB, el enlace se corta en `fuga-sin-enlace` y la alerta de seguridad debe funcionar sin enlace.

## Limitaciones (Entrega 1)

*Sin LLM en el camino crítico:* la decisión de alarma (B2) se toma con reglas sobre valores numéricos y observaciones.
*RAG: `rag.py` combina BM25 con vectores TF-IDF propios (`embeddings.py`) y fusiona ambos rankings con RRF (`_rrf`), todo en memoria. No está conectado al flujo del agente, no se indexa en pgvector y no se mide recall@k. `manuales_buscar` devuelve una lista vacía. El servidor MCP (`mcp_server.py`) se ejecuta por separado y no forma parte del compose. El agente no lee `/api/verdad` en ejecución; solo la usa `evaluacion/verdad.py` de forma offline.*
*Escenarios de órdenes y certificación:* quedan para la Entrega 2.
*Transcripción:* usa `faster-whisper` `base` int8, `beam_size=5`, y un prompt de vocabulario de planta (`PROMPT`).
*Latido F2:* mide huecos de hasta 60 s reales; la alerta de seguridad debe salir en < 30 s reales desde la nota.

La política de memoria está en docs/MEMORIA.md.

## Uso en local

- Para desarrollar en local: `docker compose -p planta ... up -d` y `docker compose -p alumno-novit ... up -d`.
- Para la corrida final: `python correccion/corregir.py --repo . --alumno etapa-final --escenarios martes-tranquilo fuga-sin-enlace --salida correccion/corridas/etapa-final`.
- Los informes quedan en `correccion/corridas/<nombre>/informe.md` y `resultado.json`.

---

*Desarrollo de Agentes IA y Software Agéntico. Formación anual, gratuita, abierta y 100% online.*
*Academia Novit 2026*
