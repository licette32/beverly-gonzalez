# Decisiones del proyecto

Fecha de registro: 2026-11-10

Este documento registra las decisiones acordadas para la Entrega 1 y las que quedan para entregas posteriores. Cada decisión indica alternativas, motivo y consecuencias.

## Alcance de la Entrega 1

**Decisión:** la Entrega 1 se corrige únicamente con los escenarios `martes-tranquilo` y `fuga-sin-enlace`, con los criterios A1, A2, A3, A4a, A4b, B1, B2, F1 y F2. Son 53 puntos medidos. Las eliminatorias aplicables son `sin_alerta_de_seguridad` y `sistema_mudo`.

**Alternativas:** implementar también órdenes, reglas de aprobación, Central 8200, `sin-luz`, `ataque`, `tormenta-perfecta` y `contratista`.

**Por qué:** el circuito de voz, detección, alerta, latido y contrato ya cubre los criterios que se corrigen esta semana. Sumar órdenes y las otras fallas aumenta el riesgo de no terminar el camino crítico.

**Consecuencias:** quedan fuera del plan semanal las órdenes, la Central 8200, la certificación, el corte de luz y los escenarios de contratista, ataque y tormenta. Se retoman en la Entrega 2.

## D1. Ejecución local

**Decisión:** la Entrega 1 corre completamente local. La nube no es requisito; si se evalúa en la Entrega 2, será opcional y asíncrona.

**Alternativas:** usar modelos en la nube desde la primera entrega.

**Por qué:** la corrección corre en una máquina con 4 CPU y 8 GB, sin GPU, y la planta exige funcionar sin enlace y sin dependencias externas.

**Consecuencias:** el sistema debe arrancar con modelos locales y no puede depender de Internet durante la corrección.

## D2. Transcripción

**Decisión:** usar `faster-whisper` con modelo `small` en int8 y respaldo `base`. El modelo se predescarga en la imagen o en un volumen.

**Alternativas:** `base` solamente; `medium`; transcripción en la nube.

**Por qué:** `small` ofrece una mejora razonable en español sin el costo de `medium`. `base` queda como respaldo si el tiempo o la memoria no alcanzan. La descarga en caliente no es aceptable en corrección.

**Consecuencias:** hay que medir el tiempo real de transcripción. Si una nota tarda más de aproximadamente 20 segundos, se revisa el modelo o la estrategia.

## D3. Modelo de lenguaje

**Decisión:** usar Qwen2.5 3B Q4_K_M como modelo principal y Llama 3.2 3B o 1.5B como respaldo. No usar modelos de 9B.

**Alternativas:** Qwen 7B/9B, Llama 3.1 8B, modelos en la nube.

**Por qué:** un modelo de 3B cuantizado entra en el presupuesto de memoria junto con Whisper, el agente y PostgreSQL. Los modelos de 9B no dejan margen para el resto del sistema en 8 GB.

**Consecuencias:** las tareas de interpretación deben estar acotadas con esquemas y reglas deterministas. El modelo no decide seguridad ni aprobaciones.

## D4. Detección determinista

**Decisión:** las reglas de seguridad S1-S4, los límites de alarma y la clasificación de novedad se implementan en código. El LLM solo interpreta el texto y propone datos estructurados.

**Alternativas:** pedirle al LLM que decida si hay una situación insegura o si corresponde escalar.

**Por qué:** la seguridad no puede depender de la variabilidad de un modelo. La corrección mide alertas, tiempos y falsos positivos.

**Consecuencias:** S1 es pérdida con proyección de agua a presión; S2 es olor a gas; S3 es humo u olor a quemado en un motor; S4 es persona lesionada. La detección debe ser rápida y no esperar al LLM.

## D5. Idempotencia y persistencia

**Decisión:** usar identificadores deterministas con UUIDv5, restricciones `unique`, una tabla de outbox y un registro de eventos y órdenes.

**Alternativas:** generar UUID aleatorios y confiar en que no se repitan; publicar directo sin outbox.

**Por qué:** la corrección puede repetir mensajes y el sistema debe sobrevivir reinicios sin duplicar eventos, órdenes ni alertas.

**Consecuencias:** cada evento y cada orden tiene una clave estable. El outbox permite reintentar publicaciones sin crear duplicados.

## D6. Orquestación

**Decisión:** usar un pipeline asíncrono propio para MQTT, colas, reglas y persistencia. Usar LangChain para llamadas al modelo y salidas estructuradas. No usar LangGraph en la Entrega 1.

**Alternativas:** LangGraph desde el inicio; un framework de agentes completo.

**Por qué:** el camino crítico es un flujo de eventos con reglas claras, no un grafo de agentes. LangGraph agrega complejidad que no se corrige en esta entrega.

**Consecuencias:** el código debe separar recepción, transcripción, interpretación, detección y publicación. LangGraph queda para una entrega posterior si aporta valor.

## D7. Transcripción completa antes del detector

**Decisión:** recibir el audio completo, transcribir la nota entera, ejecutar inmediatamente el detector determinista S1-S4 y recién después lanzar el LLM para estructurar el parte.

**Alternativas:** transcribir en parciales y lanzar el detector sobre la transcripción parcial.

**Por qué:** evita falsos positivos y negativos por frases incompletas, y simplifica el flujo. La alerta de seguridad se decide con la transcripción completa y reglas deterministas.

**Consecuencias:** la latencia de la alerta depende de la transcripción completa. Si se mide que la transcripción supera aproximadamente 20 segundos, se rediscute la estrategia. La alerta y el aviso de tablet deben salir dentro de los 30 segundos reales que exige B2.

## D8. Ollama y red

**Decisión:** ejecutar Ollama como servicio separado en la red `planta-lan`, con `OLLAMA_HOST=http://ollama:11434`, y agregar `ollama` a `NO_PROXY`. Si Ollama corre en el host, usar `host.docker.internal` y el mismo bypass de proxy.

**Alternativas:** compartir el localhost del contenedor; salir por el proxy para llegar a Ollama.

**Por qué:** el contenedor del agente no comparte el localhost del host y el proxy de la planta no debe interceptar el tráfico interno.

**Consecuencias:** el compose debe declarar el servicio de Ollama o la configuración del host, y el sistema debe esperar a que Ollama esté disponible.

## D9. RAG

**Decisión:** el RAG documental queda como mínimo o diferido. Para la Entrega 1, el catálogo de tareas y repuestos se resuelve con YAML o SQL, no con recuperación semántica.

**Alternativas:** implementar pgvector, chunking, búsqueda híbrida y reranking antes del camino crítico.

**Por qué:** los criterios corregidos esta semana no dependen de RAG. La recuperación documental es revisión manual y puede esperar.

**Consecuencias:** no se bloquea la entrega por embeddings. El RAG se retoma cuando A1-A4b, B1, B2, F1 y F2 estén estables.

## D10. Contrato por pip

**Decisión:** instalar `planta_contrato` desde el repositorio del curso con pip, fijando la versión o el commit. No copiar los modelos al proyecto.

**Alternativas:** copiar `planta_contrato` al repositorio; redefinir los modelos a mano.

**Por qué:** el contrato es la fuente de verdad y copiarlo permite que se desincronice. La corrección valida contra la versión oficial.

**Consecuencias:** la imagen necesita `git` para instalar desde GitHub. Se debe usar la URL de `academia2026-tp`, no la de `academia2026-planta` que aparece en algunos documentos.

## D11. MQTT

**Decisión:** publicar eventos, órdenes y mensajes de tablet con QoS 1 y sin `retain`. Publicar `sistema/estado` cada 30 segundos. No publicar mensajes innecesarios.

**Alternativas:** QoS 0; `retain` en todos los topics; latidos más frecuentes.

**Por qué:** QoS 1 reduce pérdidas sin exigir exactamente-once. El latido cada 30 segundos cumple F2 y no satura el broker. `retain` solo corresponde a estados que la planta necesita al reconectar.

**Consecuencias:** el cliente MQTT debe manejar reintentos y duplicados. El latido debe ser independiente de la transcripción y del LLM.

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

**Decisión:** el servicio `agente` recibe `HTTP_PROXY=http://enlace:3128`, `HTTPS_PROXY=http://enlace:3128` y `NO_PROXY=broker,sim,localhost`, como exige el anexo.

**Alternativas:** no configurar proxy y depender del entorno del host.

**Por qué:** la red de la planta exige el proxy para salir y el agente debe evitar usarlo para el broker y los servicios internos.

**Consecuencias:** si más adelante se agrega Ollama, hay que sumar `ollama` a `NO_PROXY`. El compose deja estos valores configurables por `.env`.

## Reparto de trabajo

**Decisión:** Beverly escribe el detector S1-S4 y la regla B1. El asistente aporta la estructura, los casos de prueba y la revisión.

**Por qué:** son las partes donde la comprensión de las reglas de planta y la defensa oral importan más.

**Consecuencias:** antes de implementar esas piezas se acuerdan la estructura de datos, los casos límite y los resultados esperados. El resto del esqueleto se implementa y se prueba primero.

## Esqueleto de la Entrega 1

El primer paso es un servicio `agente` que se conecta al broker, valida los mensajes de entrada con `planta_contrato` y publica `sistema/estado` cada 30 segundos desde un hilo independiente. Todavía no procesa audio, no detecta fallas y no genera partes.

## Reglas operativas de la Entrega 1

**Latido independiente:** `sistema/estado` se publica desde un hilo o proceso dedicado. La transcripción, la descarga de audio y el LLM nunca pueden bloquearlo. F2 mide huecos de hasta 60 segundos reales.

**Validación antes de publicar:** todo mensaje de salida se construye con un modelo Pydantic de `planta_contrato` y se valida antes de publicarlo. Si no valida, no se publica y se registra el error.

**Notas de seguridad:** también necesitan borrador y confirmación del operador. Cuentan en A2 y A3, además de disparar B2.

**B1:** se replica la regla del corrector: se excluyen las observaciones `"parada, en reserva"` y `"parada por mantenimiento"`; se comparan `presion_descarga_local` con `presion_descarga` y `presion_diferencial` con `presion_diferencial`; se convierten `psi` y `bar` a kg/cm²; se aplican alarmas altas y bajas; una nota sin ítems espera `SinNovedad` con equipo vacío.

## Reloj de corrección

**Decisión:** usar el reloj por eventos de la rúbrica: `rapida: 1800`, `lenta: 5`, `silencio_s: 5`, `minimo_s: 3`, `maximo_s: 120`.

**Cómo funciona:** entre eventos la planta avanza a ×1800 (1 segundo real = 30 minutos simulados). Cuando ocurre algo que requiere atención, baja a ×5 (1 segundo real = 5 segundos simulados). Vuelve a ×1800 cuando pasaron al menos 3 segundos reales desde la frenada, el sistema lleva 5 segundos reales sin publicar mensajes que no sean latidos y no hay una pregunta de tablet esperando respuesta. Si se llega a 120 segundos reales desde la frenada, vuelve a ×1800 aunque no se cumplan las condiciones.

**Consecuencias:** una nota tiene una ventana lenta de 5 segundos reales si el sistema no publica nada, se estira 5 segundos después del último mensaje y tiene un tope de 120 segundos reales. Para B2, la alerta y el aviso de tablet deben salir dentro de 30 segundos reales desde la nota, aunque la ventana lenta pueda durar más.
