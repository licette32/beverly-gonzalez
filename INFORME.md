# INFORME TÉCNICO – Entrega 2

## Resumen

La Entrega 2 conserva el camino crítico determinista de la Entrega 1 y agrega órdenes de trabajo, el paso revisor, la traza de decisiones, el control de reintentos/deadline/loops, la durabilidad ante corte y el análisis LLM opcional. Todo lo que decide estado, tareas, repuestos o citas sigue siendo código determinista.

El LLM es opcional y queda apagado por defecto (`LLM_HABILITADO=false`). **No se ejecutó con un modelo real** durante la verificación: las mediciones de `analisis_llm` usan el fake de Ollama de `tests/test_llm.py`. No hay modelo de visión: las fotos no se descargan ni se asocian a una fila; la URL de la foto se incluye en `observacion` para el aviso S1. Ollama no está en el compose principal.

## 1. Modelos y medición

Los valores de tokens, costo y duración salen de filas reales de `decisiones` usando `RegistroDecisionesMemoria` en la suite de tests. La corrida de verificación produjo `analisis_llm` con `prompt_eval_count=10` y `eval_count=5` (15 tokens), `version="ministral-3:3b-v1"` y `duracion_ms=4`; las filas `evaluar` y `validar_orden_publicable` del camino determinista dieron 0 tokens, costo 0 y `duracion_ms=0`. Con `LLM_HABILITADO=false`, la fila `analisis_llm` quedó con `modelo="reglas"`, `resultado="deshabilitado"`, 0 tokens, costo 0 y `duracion_ms=0`.

| Tarea | Modelo | Versión | Parámetros | Hardware | Tokens | Costo USD | Duración |
|-------|--------|---------|------------|----------|-------:|----------:|---------:|
| `evaluar` / `validar_orden_publicable` (`reglas-python`) | `reglas` | código del repo, revisión `7adf6e1` | reglas puras; sin LLM; `extra="forbid"` en contratos | PC de planta: 4 CPU / 8 GB, sin GPU | 0 | 0 | 0 ms medido en la corrida de verificación |
| `analisis_llm` habilitado | `ministral-3:3b` | `ministral-3:3b-v1` (respuesta del fake) | `LLM_HABILITADO=true`, `LLM_MODELO=ministral-3:3b`, `/api/chat`, `stream=False`, JSON Schema, `LLM_TIMEOUT_S=120` | CPU local sin GPU; verificación con fake Ollama en la suite | 15 = 10 entrada + 5 salida | 0 local; 0,00002 con 1 USD/MTok entrada y 2 USD/MTok salida | 4 ms medido en la corrida de verificación |
| `analisis_llm` deshabilitado | `reglas` | no aplica | `LLM_HABILITADO=false`; no se llama a Ollama | PC de planta: 4 CPU / 8 GB, sin GPU | 0 | 0 | 0 ms medido en la corrida de verificación |

Notas sobre la tabla:

- `tokens` es la suma de `prompt_eval_count` y `eval_count`, como la guarda `agente/sistema/llm.py` en la columna `tokens` de `decisiones`.
- `costo_usd` es 0 cuando las tarifas por millón de tokens están en 0 (configuración por defecto para un LLM local). Si se setean `LLM_COSTO_USD_POR_MTOK_ENTRADA` y `LLM_COSTO_USD_POR_MTOK_SALIDA`, se calcula con esos valores; la corrida con fake usó 1 y 2 USD/MTok para verificar la fórmula.
- La duración de las filas deterministas puede ser 0 ms porque se mide con resolución de milisegundos. No es una estimación: es el valor registrado en `duracion_ms`.
- La justificación devuelta por el LLM se recorta a 500 caracteres antes de registrarse (`JUSTIFICACION_MAX_CARACTERES` en `llm.py`), con test en `tests/test_llm.py`.

### Transcripción y modelo siempre activo

- **Motor:** `faster-whisper` 1.2.1, Whisper `base` int8, `beam_size=5`, `cpu_threads=2`, `OMP_NUM_THREADS=2`, `language="es"` y prompt de vocabulario de planta.
- **Medición previa:** en i3-1115G4 de 2 núcleos, `base` tarda 4,46 s con beam 1 y 5,41 s con beam 5 sobre una nota de 11,24 s; `small` tarda 19,77 s y 24,38 s y queda descartado.
- **Hardware de referencia:** PC sin GPU, 4 núcleos y 8 GB; el compose limita el agente a 2 CPU / 2 GB y Postgres a 0,5 CPU / 1 GB.
- Whisper no produce tokens de LLM ni costo por API: ejecuta localmente en CPU.

## 2. Qué se midió y qué no

Se midió:

- Latencia de transcripción con Whisper `base` int8 en CPU local.
- Tokens, costo y duración de `analisis_llm` con fake de Ollama, tanto habilitado como deshabilitado.
- Filas deterministas de `reglas.evaluar` y `validar_orden_publicable` desde `decisiones`.
- Recall@k del RAG sobre 701 fragmentos y 71 preguntas.

No se midió:

- Un LLM real (`ministral-3:3b` u otro) ejecutándose en Ollama: la verificación usa solo un fake.
- Latencia, consumo de memoria o calidad de respuestas de Ollama en la PC de 4 CPU / 8 GB.
- Modelos de visión: no hay modelo, no se descargan fotos y no hay asociación foto-fila.
- El monto de certificación desde CT-SVP-2025; la certificación G3 queda para revisión manual.

Con un LLM real habría que medir latencia p95, memoria residente, estabilidad del JSON estructurado y tokens reales por escenario; con visión real habría que medir precisión de extracción desde foto y su efecto en A2/A3, hoy limitados por el corrector oficial.

## 3. Recuperación documental

La comparación ya estaba reportada en el INFORME de la Entrega 1:

| Métrica | Este sistema | BM25 |
|---------|-------------:|-----:|
| hit@5 | 0,831 | 0,850 |
| recall@5 | 0,702 | 0,660 |
| Rev. C antes que D | 0/71 | n/d |

`hit@5` queda levemente por debajo de BM25 y `recall@5` por encima. El `0/71` de la Rev. C se debe al filtro `vigente`, no a una preferencia aprendida. `manuales_buscar` está expuesto por MCP y es usado por el flujo para citar manuales vigentes en las causas; el análisis con LLM opcional no cambia esa recuperación.

## 4. Resultados del corrector

Última corrida local disponible:

| Criterio | Última corrida |
|----------|---------------:|
| A1 Cobertura | 88 % |
| A2 Borrador al primer intento | 58 % |
| A3 Parte final correcto | 64 % |
| A4a Pregunta cuando hace falta | 100 % |
| A4b No pregunta de más | 100 % |
| B1 Sin novedad / Escalado | 92 % |
| B2 Alerta de seguridad | 100 % |
| E1 Sigue andando sin enlace | 100 % |
| E2 Pendientes visibles | 50 % |
| E3 Sin duplicados | 100 % |
| F1 Mensajes válidos | 100 % |
| F2 Latido | 100 % |

## 5. Control de reintentos, deadline y loops

| Mecanismo | Valor | Evidencia |
|-----------|-------|-----------|
| Reintentos de tools HTTP de solo lectura | `REINTENTOS_TOOL_LECTURA=2`, `ESPERA_REINTENTO_TOOL_S=0,5` | `tests/test_tools.py` verifica 2 intentos en timeout, 1 en 4xx y `resultado` `reintento`/`error` en `decisiones` |
| Deadline por orden | `FLUJO_LIMITE_S=600` | Antes de construir devuelve `orden=None`; después guarda la orden pendiente con `LIMITE_TIEMPO`, sin publicarla en `Topicos.ORDENES` |
| Loops | `UMBRAL_LOOP_PASOS=3` sobre `(paso, herramienta, argumentos)` y `correlation_id` | `tests/test_flujo.py` cubre corte antes/después de construir y excluye `deadline`, `loop` y `tool_timeout` de la cuenta |

El control es cooperativo: se verifica entre etapas, sin hilos que interrumpan llamadas en vuelo. Los reintentos aplican a timeout, conexión y HTTP 5xx; no a 4xx ni a errores de parseo. Los errores finales quedan con `reintentable=False`.

## 6. Trazabilidad y verificación cruzada

La tabla `decisiones` tiene `id`, `correlation_id`, `tarea`, `paso`, `modelo`, `herramienta`, `argumentos`, `tokens`, `costo_usd`, `duracion_ms` y `creado_ts`. El `correlation_id` del flujo de órdenes es `evento.id`. Los modelos `reglas`, `humano` y `control` aparecen según el origen de la decisión; `control` se usa para `deadline`, `loop`, `tool_timeout` y cada intento de herramienta.

Evidencia de git usada para cruzar afirmaciones:

- `7adf6e1` control: reintentos acotados, deadline por orden y detección de loops
- `193a92a` tablet: resolver equipo y foto en aviso S1; documentar límite del corrector
- `43c46f1` LLM: análisis opcional que prioriza causas, con fallback determinista
- `05b16a4` trazabilidad: registrar cada paso de decisión de una orden
- `8ce9036` flujo: paso revisor de citas y repuestos antes de decidir la orden
- `607c0c2` latido: sonda de enlace real y durabilidad ante corte

La consulta al fake repo reproducida para la tabla fue `RegistroDecisionesMemoria` vía `tests/test_llm.py`, filtrando `analisis_llm`, `evaluar` y `validar_orden_publicable` por `correlation_id="E-1"`.

## 7. Conclusión

Se midieron la transcripción local, los tokens, el costo y la duración del análisis LLM con fake de Ollama, las filas deterministas de `decisiones`, la recuperación documental, los resultados del corrector y el control de reintentos, deadline y loops.

No se midió un LLM real: el adaptador es opcional y viene apagado por defecto (`LLM_HABILITADO=false`), Ollama no está en el compose principal y la verificación usó solo un fake. Tampoco se midió visión: no hay modelo de visión, las fotos no se descargan ni se asocian a una fila.

Con un LLM real se podrían medir latencia p95, memoria residente, estabilidad del JSON estructurado y tokens por escenario. Con un modelo de visión real se podría medir precisión de extracción desde fotos y su efecto en A2/A3, hoy limitados por el corrector oficial.
