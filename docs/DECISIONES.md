# Decisiones del proyecto

Fecha de registro: 2026-11-10

Este documento registra las decisiones acordadas para la Entrega 2. Cada decisión indica alternativas, motivo y consecuencias.

## Alcance de la Entrega 1

**Decisión:** la Entrega 1 se corrige únicamente con los escenarios `martes-tranquilo` y `fuga-sin-enlace`, con los criterios A1, A2, A3, A4a, A4b, B1, B2, F1 y F2. Son 53 puntos medidos. Las eliminatorias aplicables son `sin_alerta_de_seguridad` y `sistema_mudo`.

**Alternativas:** implementar también órdenes, reglas de aprobación, Central 8200, `sin-luz`, `ataque`, `tormenta-perfecta` y `contratista`.

**Por qué:** el circuito de voz, detección, alerta, latido y contrato ya cubre los criterios que se corrigen esta semana. Sumar órdenes y las otras fallas aumenta el riesgo de no terminar el camino crítico.

**Consecuencias:** quedan fuera del plan semanal las órdenes, la Central 8200, la certificación, el corte de luz y los escenarios de contratista, ataque y tormenta. Se retoman en la Entrega 2.

## D1. Ejecución local

**Decisión:** la Entrega 2 corre completamente local. La nube no es requisito.

**Alternativas:** usar modelos en la nube.

**Por qué:** la corrección corre en una máquina con 4 CPU y 8 GB, sin GPU, y la planta exige funcionar con enlace intermitente y sin nube.

**Consecuencias:** el sistema debe arrancar con modelos locales y no puede depender de Internet durante la corrección.

## D2. Transcripción

**Decisión:** usar `faster-whisper` con modelo `base` en int8, `beam_size=5`, `cpu_threads=2` y `OMP_NUM_THREADS=2`. El modelo se hornea en la imagen y se carga con `local_files_only=True`. El prompt de vocabulario de planta `PROMPT` se pasa a la transcripción para mejorar reconocimiento de equipos y valores.

**Alternativas:** `small` con beam 5; `small` con beam 1; `medium`; transcripción en la nube.

**Por qué:** medido en la i3 de 2 núcleos con la misma nota de 11,24 s y modelo caliente, `small` con beam 1 tardó 19,77 s y `base` con beam 1 tardó 4,46 s; con beam 5, `base` tardó 5,41 s y `small` 24,38 s. `small` no entra en el presupuesto de B2 ni con beam 1. `base` con `OMP_NUM_THREADS=2` evita la sobresuscripción de CTranslate2 y deja la transcripción dentro del camino crítico. La descarga en caliente no es aceptable en corrección.

**Consecuencias:** la alerta y el borrador usan la transcripción completa de `base`. Si una nota supera aproximadamente 20 segundos, se revisa el modelo o los recursos. La imagen crece y el build necesita red para descargar el modelo.

**Nota:** Entrega 1 sin LLM en el camino crítico; interpretación determinista.

## D3. Sin modelo de lenguaje en la Entrega 1

**Decisión:** en la Entrega 1 no se utiliza ningún modelo de lenguaje (LLM). La interpretación de partes, la detección de seguridad y la clasificación de novedades se implementan como reglas deterministas en código. El modelo Whisper solo se usa para transcripción local.

**Alternativas:** para la Entrega 2 se podría integrar un modelo LLM local opcional detrás del broker.

**Por qué:** el presupuesto de memoria (8 GB) y la necesidad de latencia predecible (B2 < 30 s) hacen impráctico un LLM en el camino crítico. La arquitectura Whisper + reglas garantiza predicción de tiempo y decisiones reproducibles.

**Consecuencias:** las tareas de interpretación están acotadas con esquemas Pydantic y reglas fijas; no hay variabilidad en las decisiones de seguridad ni en la clasificación de novedades.

## D4. (sin uso)

Número reservado; no hay decisión registrada.

## D5. Idempotencia y persistencia

**Decisión:** usar identificadores deterministas con UUIDv5, restricciones `unique`, una tabla de outbox y un registro de eventos y órdenes.

**Alternativas:** generar UUID aleatorios y confiar en que no se repitan; publicar directo sin outbox.

**Por qué:** la corrección puede repetir mensajes y el sistema debe sobrevivir reinicios sin duplicar eventos, órdenes ni alertas.

**Consecuencias:** cada evento y cada orden tiene una clave estable. El outbox permite reintentar publicaciones sin crear duplicados.

## D6. Orquestación

**Decisión:** pipeline propio con hilos y colas: descarga en un pool, transcripción en un worker, coordinador de partes y latido en un hilo aparte. En la Entrega 1 el camino crítico no usa un modelo de lenguaje: la detección de seguridad, la extracción del parte, las ambigüedades y las correcciones del operador son deterministas. Por eso no se usa LangChain ni LangGraph.

**Alternativas:** LangChain para llamadas al modelo y salidas estructuradas; LangGraph desde el inicio; un framework de agentes completo.

**Por qué:** con 2 núcleos y Whisper dentro del camino crítico, un LLM local no entra en los 30 s de B2. Las reglas deterministas son auditables y reproducibles.

**Consecuencias:** el compose no declara ningún servicio de modelo de lenguaje. Si una entrega futura incorpora un LLM, entra detrás del coordinador sin tocar la detección de seguridad. Las tools de solo lectura y el servidor MCP quedan listos para ese caso.

## D7. Transcripción completa antes del detector

**Decisión:** recibir el audio completo, transcribir la nota entera, ejecutar inmediatamente el detector determinista S1-S4 y recién después estructurar el parte con reglas deterministas.

**Alternativas:** transcribir en parciales y lanzar el detector sobre la transcripción parcial.

**Por qué:** evita falsos positivos y negativos por frases incompletas, y simplifica el flujo. La alerta de seguridad se decide con la transcripción completa y reglas deterministas.

**Consecuencias:** la latencia de la alerta depende de la transcripción completa. Si se mide que la transcripción supera aproximadamente 20 segundos, se rediscute la estrategia. La alerta y el aviso de tablet deben salir dentro de los 30 segundos reales que exige B2.

## D8. Ollama y red

**Decisión:** en la Entrega 2 el adaptador LLM es opcional y está apagado por defecto (`LLM_HABILITADO=false`). Si se habilita, usa Ollama en `/api/chat`; Ollama no tiene servicio en el compose principal. La configuración de proxy (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`) es solo para el agente y el host local de Ollama debe figurar en `NO_PROXY`.

**Alternativas:** un LLM en el camino crítico; declarar Ollama como servicio del compose principal.

**Por qué:** el sistema debe funcionar con 4 CPU, 8 GB, sin GPU y con enlace intermitente; el camino crítico sigue siendo determinista y no depende de la nube.

**Consecuencias:** sin LLM o con enlace caído para un host externo, el flujo sigue con reglas; el análisis pendiente se cuenta en el latido y no se reejecuta al volver el enlace.

## D9. RAG documental

**Decisión:** el RAG documental se indexa en pgvector, pero sigue fuera del camino crítico. `embeddings.py` reemplaza el TF-IDF de vocabulario variable por un hashing determinista de tokens (`zlib.crc32(token) % 4096`) con pesos IDF sobre las posiciones, porque no hay un modelo de embeddings en la lista cerrada y así la dimensión queda fija para la columna `vector(4096)`. `indice_pg.py` crea la extensión y la tabla `fragmentos`, y hace altas idempotentes (`ON CONFLICT (id) DO UPDATE`). `main.py` lanza `sistema.indexar` como proceso aparte con baja prioridad, sin bloquear el latido ni el worker. `rag._Retriever` usa `indice_pg.buscar` (distancia coseno `<=>` con `statement_timeout`) cuando hay `POSTGRES_DSN` y el índice responde; si falla o no hay filas, cae al índice en memoria. La búsqueda híbrida BM25 + vectorial con RRF (`_rrf`) se mantiene. No está conectado a `coordinador.py`: el flujo de notas no consulta RAG. Los límites, el stock y el catálogo de tareas no salen de RAG: se consultan por API, SQL o YAML. DIM = 4096; pgvector no permite índices HNSW/IVFFlat por encima de 2000 dimensiones, así que la búsqueda es exacta (sin índice), válida para ~700 fragmentos.

**Alternativas:** dejar solo el índice en memoria; instalar un modelo de embeddings externo; indexar de forma sincrónica en el arranque.

**Por qué:** pgvector ya está en la imagen de Postgres y da persistencia sin agregar un servicio; el hashing evita otra dependencia de modelo y mantiene la dimensión fija. Indexar en un proceso aparte conserva el arranque y el latido.

**Consecuencias:** medición offline sobre 701 fragmentos y 71 preguntas: hit@5 0,831 (base BM25 0,850) y recall@5 0,702 (base 0,660); Rev. C antes que D: 0/71 por el filtro `vigente`. `manuales_buscar` ahora filtra por metadatos (tipo, doc, vigente) e id de sección dedicada; está expuesto en el servidor MCP `mcp_server.py`. El chunking y el reranking quedan pendientes y declarados.

## D10. Contrato por pip

**Decisión:** instalar `planta_contrato` desde el repositorio del curso con pip, fijando la versión o el commit. No copiar los modelos al proyecto.

**Alternativas:** copiar `planta_contrato` al repositorio; redefinir los modelos a mano.

**Por qué:** el contrato es la fuente de verdad y copiarlo permite que se desincronice. La corrección valida contra la versión oficial.

**Consecuencias:** la imagen necesita `git` para instalar desde GitHub. Se debe usar la URL de `academia2026-tp`, no la de `academia2026-planta` que aparece en algunos documentos.

## D11. MQTT

**Decisión:** publicar eventos, órdenes y mensajes de tablet con QoS 1 y sin `retain`. Publicar `sistema/estado` cada 30 segundos. No publicar mensajes innecesarios.

**Alternativas:** QoS 0; `retain` en todos los topics; latidos más frecuentes.

**Por qué:** QoS 1 reduce pérdidas sin exigir exactamente-once. El latido cada 30 segundos cumple F2 y no satura el broker. `retain` solo corresponde a estados que la planta necesita al reconectar.

**Consecuencias:** el cliente MQTT debe manejar reintentos y duplicados. El latido debe ser independiente de la transcripción y del procesamiento del parte.

## D12. PostgreSQL

**Decisión:** usar PostgreSQL 16 con tablas para eventos, órdenes, outbox, pendientes y auditoría. No usar SQLite como base de producción.

**Alternativas:** SQLite embebido; almacenamiento en memoria.

**Por qué:** la corrección puede reiniciar el sistema y necesita conservar estado, idempotencia y pendientes. PostgreSQL es el requisito del TP y permite consultas y restricciones.

**Consecuencias:** el compose debe incluir PostgreSQL y el sistema debe aplicar migraciones al arrancar.

## D13. Central de mantenimiento

**Decisión:** la Central 8200 no forma parte de la Entrega 1. Queda para la entrega de órdenes.

**Alternativas:** implementarla ahora junto con el esqueleto.

**Por qué:** el corrector de la Entrega 1 no mide aprobación humana ni certificación. Sumarla ahora distrae del camino crítico.

**Consecuencias:** el sistema de esta entrega no necesita pantalla de aprobación. La operación de órdenes se retoma después.

## D14. Verdad de la planta

**Decisión:** el sistema nunca lee `/api/verdad` ni `/api/correccion`. Solo usa el contrato MQTT.

**Alternativas:** consultar la API para obtener la verdad de campo.

**Por qué:** leer la verdad es hacer trampa y la planta cierra esos endpoints en modo corrección.

**Consecuencias:** toda la información debe venir de sensores, notas, cierres, energía y respuestas del operador.

## D15. Audio

**Decisión:** descargar el WAV de 16 kHz mono desde `audio_url` con timeout y reintento. No bloquear el loop de MQTT mientras se descarga o transcribe.

**Alternativas:** procesar el audio en el mismo hilo del cliente MQTT.

**Por qué:** una descarga lenta o una transcripción larga no puede frenar el latido ni la recepción de otras notas.

**Consecuencias:** el audio se procesa en una cola o en un worker separado. El latido corre en un hilo o proceso independiente.

## D16. Proxy del agente

**Decisión:** el servicio `agente` recibe `HTTP_PROXY=http://enlace:3128`, `HTTPS_PROXY=http://enlace:3128` y `NO_PROXY=broker,sim,localhost,postgres`, como exige el anexo.

**Alternativas:** no configurar proxy y depender del entorno del host.

**Por qué:** la red de la planta exige el proxy para salir y el agente debe evitar usarlo para el broker y los servicios internos.

**Consecuencias:** si más adelante se agrega Ollama, hay que sumar `ollama` a `NO_PROXY`. El compose deja estos valores configurables por `.env`.

## D17. Worker de notas y alerta de seguridad

**Decisión:** procesar cada `NotaRecorrida` en una cola y un hilo aparte. El hilo descarga el audio, lo transcribe, ejecuta el detector y publica un `EventoSistema` de tipo `AlertaSeguridad` por categoría y un `MensajeTablet` de aviso por nota. El hilo de MQTT solo valida y encola; el latido corre en su propio hilo.

**Alternativas:** descargar, transcribir y detectar dentro del callback de MQTT.

**Por qué:** una descarga lenta o una transcripción de varios segundos no puede bloquear la recepción ni el latido.

**Consecuencias:** la cola absorbe ráfagas. El aviso usa `espera_respuesta=False`, `nota_ids=[nota.id]` y una fila `condicion_insegura` con `valor=None`; el evento usa `origen="parte"`, `nota_ids=[nota.id]` e id determinista por nota y categoría. Se loguean descarga, transcripción, detección, publicación y total desde la llegada.

## D18. Whisper horneado, precalentado y recursos

**Decisión:** hornear `faster-whisper` base int8 en la imagen, cargarlo y hacer una transcripción de calentamiento. Usar `language="es"`, `beam_size=5`, `cpu_threads=2`, `OMP_NUM_THREADS=2` e `init: true`. El prompt de vocabulario de planta `PROMPT` se incluye en la transcripción. Suscribir y arrancar el latido antes de `precargar()`: las notas se reciben y descargan mientras el modelo carga, y `transcribir()` espera el evento `_listo`. Si la precarga falla, el evento se setea igual para desbloquear al worker. Subir el agente a 2 CPU y 2 GB.

**Alternativas:** `small` con beam 5; publicar el primer latido después de la precarga; descargar el modelo al arrancar; usar 1 CPU/1 GB; calentar con la primera nota real.

**Por qué:** en la i3 de 2 núcleos `small` con beam 1 tardó 19,77 s y `base` con beam 1 tardó 4,46 s para la misma nota; el calentamiento deja la primera inferencia dentro de B2. `init: true` evita el contenedor zombie. El latido y la suscripción antes de la precarga mantienen F2 y evitan perder notas si la carga tarda. La precarga fallida no debe colgar el hilo de transcripción.

**Consecuencias:** la imagen crece y el build necesita red para descargar el modelo. Si el modelo no está en la caché, el agente falla al arrancar en vez de descargarlo durante la corrección. El primer latido sale antes de que el modelo esté listo, pero las notas quedan encoladas y se transcriben cuando `_listo` se setea. El agente usa 2 CPU y 2 GB del presupuesto total.

## Esqueleto de la Entrega 1

El primer paso es un servicio `agente` que se conecta al broker, valida los mensajes de entrada con `planta_contrato` y publica `sistema/estado` cada 30 segundos desde un hilo independiente. Todavía no procesa audio, no detecta fallas y no genera partes.

## Reglas operativas de la Entrega 1

**Latido independiente:** `sistema/estado` se publica desde un hilo o proceso dedicado. La transcripción, la descarga de audio y el procesamiento del parte nunca pueden bloquearlo. F2 mide huecos de hasta 60 segundos reales.

**Validación antes de publicar:** todo mensaje de salida se construye con un modelo Pydantic de `planta_contrato` y se valida antes de publicarlo. Si no valida, no se publica y se registra el error.

**Notas de seguridad:** también necesitan borrador y confirmación del operador. Cuentan en A2 y A3, además de disparar B2.

**B1:** se replica la regla del corrector: se excluyen las observaciones `"parada, en reserva"` y `"parada por mantenimiento"`; se comparan `presion_descarga_local` con `presion_descarga` y `presion_diferencial` con `presion_diferencial`; se convierten `psi` y `bar` a kg/cm²; se aplican alarmas altas y bajas; una nota sin ítems espera `SinNovedad` con equipo vacío.

## Reloj de corrección

**Decisión:** usar el reloj por eventos de la rúbrica: `rapida: 1800`, `lenta: 5`, `silencio_s: 5`, `minimo_s: 3`, `maximo_s: 120`.

**Cómo funciona:** entre eventos la planta avanza a ×1800 (1 segundo real = 30 minutos simulados). Cuando ocurre algo que requiere atención, baja a ×5 (1 segundo real = 5 segundos simulados). Vuelve a ×1800 cuando pasaron al menos 3 segundos reales desde la frenada, el sistema lleva 5 segundos reales sin publicar mensajes que no sean latidos y no hay una pregunta de tablet esperando respuesta. Si se llega a 120 segundos reales desde la frenada, vuelve a ×1800 aunque no se cumplan las condiciones.

**Consecuencias:** una nota tiene una ventana lenta de 5 segundos reales si el sistema no publica nada, se estira 5 segundos después del último mensaje y tiene un tope de 120 segundos reales. Para B2, la alerta y el aviso de tablet deben salir dentro de 30 segundos reales desde la nota, aunque la ventana lenta pueda durar más.

## D19. Centinela SIN-EQUIPO, build oficial y prompt de transcripción

**Decisión:** en el cable (contrato `FilaParte.tag: str`, obligatorio) un ítem sin equipo se publica con el centinela `SIN-EQUIPO`; internamente `ItemParte.tag` es `None` y el evento B1 se publica con `equipo=None`. El build oficial es `docker compose build` desde el repositorio, con la imagen `pgvector/pgvector:pg16` para Postgres. El `PROMPT` de `transcripcion.py` contiene solo vocabulario de la planta, nunca frases de las notas de los escenarios.

**Alternativas:** relajar el contrato para aceptar `tag` nulo; usar la imagen local `alumno-novit-agente:latest` con construcción previa (descartado).

**Por qué:** el contrato no admite `tag` nulo y no se modifica. El build limpio es lo que va a ejecutar el corrector. Un prompt con frases de escenario sería sobreajuste a la corrección.

**Consecuencias:** el repositorio no contiene `Dockerfile.a-test` ni imágenes locales, y `.gitignore` excluye corridas y volcados. El `PROMPT` es parte del código fuente y viaja con el repositorio.

## D20. Registro de decisiones

**Decisión:** cada paso relevante de una orden se registra en la tabla `decisiones`. La correlación del flujo es `correlation_id = evento.id`; para órdenes ya persistidas se usa `evento_ids[0]` y, como último recurso, `orden.id`. El registro es fail-open: si no hay repositorio o falla la escritura, se loguea y el flujo continúa.

| Columna | Contenido |
|---|---|
| `id` | UUIDv5 determinista por `correlation_id`, `paso`, secuencia y timestamp |
| `correlation_id` | `evento.id` en el flujo de órdenes |
| `tarea` | tarea opcional asociada al paso |
| `paso` | etapa registrada: `causas_probables`, `evaluar`, `analisis_llm`, `validar_orden_publicable`, `deadline`, `loop`, `tool_timeout`, `tool:<nombre>`, etc. |
| `modelo` | `reglas`, `humano`, `control` o el modelo LLM configurado |
| `herramienta` | herramienta o código de error, cuando aplica |
| `argumentos` | JSONB con argumentos permitidos, resultado y metadatos acotados |
| `tokens` | tokens del LLM; 0 en pasos deterministas |
| `costo_usd` | costo calculado con tarifas configuradas; 0 en pasos deterministas |
| `duracion_ms` | duración real del paso |
| `creado_ts` | timestamp UTC; sirve para ordenar dentro de cada correlación |

**Retención:** no hay TTL, `DELETE`, `TRUNCATE` ni poda automática de `decisiones`. En Postgres persiste mientras exista el volumen `pgdata`; en `RegistroDecisionesMemoria` vive solo durante el proceso. Los textos libres se acotan: búsqueda de manuales guarda longitud y hash, decisiones humanas guardan longitudes y monto, y las justificaciones del LLM se recortan a 500 caracteres.

**Allowlist de `argumentos`:** la columna es JSONB libre a nivel de esquema, pero los productores aplican listas explícitas. `historian` guarda `tag`, `variable`, `desde`, `hasta`; `catalogo` y `stock` guardan `tag`; `historial_ordenes` guarda `equipo`, `orden_id`; los intentos de herramienta agregan `resultado`, `intento` y `codigo`. Las dos lecturas de materiales se distinguen con `fuente="tareas_no_estandar"` y `fuente="_cargar_materiales"`. La CLI no guarda nombres ni motivos, solo longitudes y monto.

**Modelos:** `reglas` es el default de los pasos deterministas; `humano` se usa para `aprobar`, `rechazar`, `certificar` y `observar`; `control` se usa para `deadline`, `loop`, `tool_timeout` y cada intento de herramienta. Un `analisis_llm` deshabilitado también se registra con `modelo="reglas"`.

**Por qué:** la auditoría tiene que explicar qué se decidió y cuánto costó, sin permitir que la traza altere la decisión ni que un fallo de observabilidad detenga la orden.

**Consecuencias:** las consultas se hacen por `correlation_id`, ordenadas por `creado_ts`. La detección de loops usa esas mismas filas, excluyendo `deadline`, `loop` y `tool_timeout` de la cuenta.
