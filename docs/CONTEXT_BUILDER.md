# Contexto del Builder

## Memoria

La memoria del sistema consta de las siguientes tablas reales:

- **estado_nota**: Almacena el estado actual de cada nota de recorrida, incluyendo el progreso del procesamiento, el borrador actual y la información de ambigüedades no resueltas.
- **respuestas**: Registra las respuestas del operador a las preguntas formuladas durante el procesamiento de las notas, incluyendo la respuesta texto, el ID del mensaje asociado y el estado de la misma.
- **pendientes**: Conteo de items en cola de sincronización (memoria). En Postgres no hay tabla `pendientes`; el valor se obtiene de ` repositorio.pendientes_sincronizar()` y refleja notas pendientes de escritura a Postgres. Véase `repositorio.py` `_sincronizar_pendientes`.

## Historial

El "Historial" corresponde al historial de la conversación completa, registrando:
- Todas las transcripciones de audio procesadas
- Las detecciones de seguridad (S1-S4) ocurridas
- Las preguntas formuladas al operador y sus respuestas
- Las decisiones tomadas por el agente
- Los partes generados y sus estados de evolución

## Resultados de tools

Los datos provenientes de las tools (heraldian, catálogo, stock, historial de órdenes) se almacenan en esta sección:

- **Historical data**: Valores históricos de variables de planta obtenidos del endpoint `/api/historian/{tag}/{variable}`
- **Catálogo de equipos**: Información del catálogo de planta obtenida de `/api/planta`, incluyendo tags, tipos, nombres y unidades manométricas
- **Stock actual**: Cantidad actual de cada equipo, consultable desde el YAML `agente/datos/stock.yaml`
- **Historial de órdenes**: Registro de órdenes de trabajo y su estado, obtenido desde `/api/historial-ordenes`

## Uso en prompts

Este contexto debe usarse para:
1. Identificar el estado actual de una nota de recorrida
2. Consultar datos históricos cuando el agente necesite validar lecturas
3. Mantener el registro de decisiones tomadas a lo largo de la conversación
4. Consultar el estado de stock y catálogo para formar respuestas al operador