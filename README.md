# Entrega 1 – Parte por voz y detección en planta

## Cómo levantar el sistema

1. **Levantar la planta**  
   ```bash
   docker compose -p planta -f docker-compose.yml up -d broker enlace sim visor
   ```
   Esto inicia el broker MQTT, el simulador de planta, el visor y el servicio de enlace.

2. **Levantar el agente del cursant**  
   ```bash
   docker compose -p alumno-novit -f docker-compose.yml up -d
   ```
   El agente se conecta al broker `planta-lan` y publica `sistema/estado` cada 30 s (latido F2).  
   - Imagen oficial: `novit‑agente:latest` (build `docker compose build --no-cache`).  
   - Variables de entorno (en `.env` o `docker compose`): `MQTT_HOST`, `POSTGRES_DSN`, `PREGUNTA_TIMEOUT_S=60`, `OMP_NUM_THREADS=2`.

3. **Base de datos**  
   PostgreSQL 16 con extensión `pgvector` (imagen `pgvector/pgvector:pg16`).  
   - DSN: `postgresql://novit:novit@postgres:5432/novit`.  
   - El sistema usa outbox/pendientes para idempotencia.

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
| **agente** | Recibe mensajes MQTT, descarga audio, transcribe con Whisper base int8 (beam 5 + `PROMPT`), ejecuta detectores S1‑S4, publica `EventoSistema` y `MensajeTablet`. | Usa reglas deterministas; el LLM sólo estructuriza, no decide seguridad. |
| **postgres** | Persiste eventos, órdenes, outbox, pending. | `pgvector/pgvector:pg16`; sin dependencia de Redis. |
| **planta** | Simula la central térmica, genera audios, publica sensores. | Modelo `base` + prompt `PROMPT` mejora reconocimiento de equipos y valores. |

## Limitaciones (Entrega 1)

*Sin LLM en el camino crítico:* la decisión de alarma (B2) se toma con reglas sobre valores numéricos y observaciones.
*Sin RAG ni `/api/verdad:`:* la verdad viene del contrato MQTT y del operador.
*Escenarios de órdenes y certificación:* quedan para la Entrega 2.
*Transcripción:* usa `faster‑whisper` `base` int8, `beam_size=5`, y un prompt de vocabulario de planta (`PROMPT`). Notas > 20 s de audio pueden necesitar revisión manual.
*Latido F2:* mide huecos de hasta 60 s reales; la alerta de seguridad debe salir en < 30 s reales desde la nota.

### Pol�tica de memoria

- Se recuerda cada nota completada (texto, decisiones y estado de borrador)
- En PostgreSQL persiste mientras la corrida est� activa; al cerrarse la planta,
  los datos se compactan y se conservan el �ltimo estado de cada nota.
- No se guardan transcripciones completadas hace m�s de 45 d�as (historian_rango).


## Uso en local

- Para desarrollar en local: `docker compose -p planta ... up -d` y `docker compose -p alumno-novit ... up -d`.
- Para la corrida final: `python correccion/corregir.py --repo . --alumno etapa-final --escenarios martes-tranquilo fuga-sin-enlace --salida correccion/corridas/etapa-final`.
- Los informes quedan en `correccion/corridas/<nombre>/informe.md` y `resultado.json`.

---

*Desarrollo de Agentes IA y Software Agéntico. Formación anual, gratuita, abierta y 100% online.*
*Academia Novit 2026*