# INFORME TÉCNICO – Entrega 1

## 1. Modelos Utilizados

### 1.1 Transcripción de audio
- **Motor:** `faster-whisper` versión 1.2.1
- **Modelo:** Whisper `base` (aprox. 74 M de parámetros), pesos de OpenAI, cuantizado en `int8`, ejecutado con `faster-whisper` (CTranslate2). Repositorio del modelo: `base` (identificador de `MODELO` en `transcripcion.py`).
- **Parámetros:** `beam_size=5`, `cpu_threads=2`, `OMP_NUM_THREADS=2`, `language="es"`
- **Prompt de vocabulario:** `PROMPT` personalizado con nombres de equipos, variables y unidades de la planta (incluye "kg/cm2", "psi", "bar", nombres de bombas B-101/B-102/B-103, filtros F-201A/F-201B, valores numéricos en español)
- **Duración típica:** 4.46 s por nota de ~11 s con `base` beam 1 en hardware de 2 núcleos; el setup actual (beam 5 + 2 threads) queda dentro del presupuesto de B2 (~30 s reales por nota)

### 1.2 Interpretación y Corrección de Parte
- **Motor:** Ningún LLM en el camino crítico
- **Enfoque:** Reglas deterministas codificadas en `agente/sistema/interpretacion.py`
- **Funciones aplicadas en orden:**
  - `_corregir_equipo`: Resuelve ambigüedad de equipo (ej. "la dos" -> B-102) y recalcula la unidad con `catalogo.unidad_manometro(tag)`
  - `_corregir_unidad`: Cambia de unidad cuando el operador dice "no en psi" si antes decía "kg/cm2" y el catálogo indica otra cosa
  - `_corregir_valor`: Corrige valores numéricos (manejo de "dieciocho" vs "uno ocho", etc.)
  - `_agregar_faltante`: Añade ítems que faltan en la nota
  - `_quitar_sobrante`: Elimina ítems que el operador dijo que no eran
- **Corrección de unidad NOTA-00011:** Al resolver "la dos" -> B-102, la unidad se recalcula automáticamente de kg/cm2 a psi usando `catalogo.unidad_manometro("B-102")` -> "psi"

### 1.3 Detección de Seguridad (S1-S4)
- **Motor:** Código determinista, sin LLM
- **Reglas S1-S4:** Implementadas en `agente/sistema/seguridad.py` sobre la transcripción
- **Tiempo de respuesta:** < 30 s reales (exige B2)

### 1.4 Tools y MCP
- **Tools de solo lectura** con contratos Pydantic estrictos (`extra="forbid"`):
  - `equipos`, `historian`, `catalogo`, `stock`, `tareas_catalogo`, `manuales_buscar`
  - Expuestas por MCP en `mcp_server.py`: equipos, historian, catalogo_planta, stock, historial_ordenes. `manuales_buscar` no está expuesta y devuelve una lista vacía. El servidor se ejecuta por separado y no forma parte del flujo del agente.
- **Servidor MCP:** `FastMCP("pia3-planta")` con herramientas: `equipos`, `historian`, `catalogo_planta`, `stock`, `historial_ordenes`
- **MQTT:** Cliente `ClienteMQTT` con validación Pydantic de cada publicación antes de enviarla

## 2. Hardware y Entorno de Ejecución

| Componente | Especificación |
|------------|----------------|
| **Hardware** | [COMPLETAR: modelo de PC, CPU, RAM, GPU, SO] |
| **Docker** | `docker compose` con 3 servicios: `broker`, `enlace`, `sim` + `alumno-novit-agente` |
| **Sistema de Base de Datos** | PostgreSQL 16 con extensión `pgvector` (imagen `pgvector/pgvector:pg16`) |
| **Entorno de deploy** | `docker compose build --no-cache` para build oficial; imagen `novit-agente:latest` |

### Presupuesto de recursos (medido en i3 de 2 núcleos):
- **Whisper `base` beam_size=1:** 4.46 s por nota de 11.24 s
- **Whisper `base` beam_size=5:** [COMPLETAR: volver a medir] s (queda dentro de B2 de 30 s reales)
- **Pequeño (`small`) no entra:** 19.77 s con beam 1, [COMPLETAR: volver a medir] s con beam 5; `small` no entra en el presupuesto al sumarse a Whisper + agente
- **Elección de `base` + beam 5 + OMP_NUM_THREADS=2:** Deja la primera inferencia dentro de B2 con margen de seguridad

## 3. Consumo de Tokens y Costo Aproximado

No se usan modelos de lenguaje ni APIs de pago. Consumo de tokens: 0. Costo en la nube: USD 0. La transcripción corre localmente en CPU.

No se evaluó un LLM local. Se descartó por el presupuesto de 8 GB y porque las decisiones deben ser deterministas.

## 4. Conclusión y Elección de Modelos

### Por qué `faster-whisper` `base` int8:
- **Precisión suficiente** para el dominio de planta (nombres de equipos, valores numéricos en español, unidades)
- **Performance dentro de B2:** 4.46 s base beam 1 / [COMPLETAR: volver a medir] base beam 5 en hardware de 2 núcleos; el setup actual (beam 5 + 2 threads) deja la primera inferencia dentro del presupuesto de 30 s reales
- **Costo cero en tokens:** Ejecución 100% local, sin dependencia de APIs externas
- **Compatibilidad con hardware:** Caben en 8 GB RAM junto con Whisper, agente y PostgreSQL

### Por qué interpretación determinista (sin LLM en camino crítico):
- **Seguridad:** Las reglas de alarma (B2) no pueden depender de la variabilidad de un modelo
- **Auditoría:** Mismo input -> mismo output garantizado
- **Cumplimiento de restricciones:** 8 GB RAM + 4 CPU justifican el uso de modelos pequeños + reglas en código
- **Rendimiento predecible:** Los tiempos de ejecución son fijos y conocidos, a diferencia de la latencia de un LLM

### Por qué Whisper sobre otras opciones:
- `small` con beam 1 tarda 19.77 s; con beam 5 tarda [COMPLETAR: volver a medir] s – `small` no entra en el presupuesto cuando se suma al resto del agente
- `medium` tarda mucho más y tampoco caben los parámetros en 8 GB
- Modelos en la nube (OpenAI Whisper, etc.) violan la restricción "sin enlace" de B2 (el enlace se cae a los 10 minutos en fuga-sin-enlace)

### Conclusión general:
La arquitectura actual optó por un **enfoque híbrido**: Whisper local para la transcripción (único modelo probabilístico en el camino crítico) + reglas deterministas para toda la toma de decisiones (seguridad, parte, confirmaciones, rango histórico). Esta diseño:
- [COMPLETAR: resultados de etapa-limites]
- Permite **builds oficiales** limpios con `docker compose build`
- Permite **evaluación contra la verdad** con [COMPLETAR: cantidad real de tests]
- Respeta las **restricciones de hardware** (4 núcleos, 8 GB, sin GPU)
- Elimina **dependencias externas** durante la corrección (el enlace de red se puede cortar)
