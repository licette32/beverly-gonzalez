import os

MQTT_HOST = os.getenv("MQTT_HOST", "broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
SISTEMA = os.getenv("SISTEMA_NOMBRE", "pia3-agente-planta")
HEARTBEAT_S = int(os.getenv("HEARTBEAT_S", "30"))
ENLACE_SONDA_URL = os.getenv("ENLACE_SONDA_URL", "http://enlace:8081/estado")
ENLACE_SONDA_TIMEOUT_S = float(os.getenv("ENLACE_SONDA_TIMEOUT_S", "2"))
ENLACE_SONDA_INTERVALO_S = float(os.getenv("ENLACE_SONDA_INTERVALO_S", "5"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PLANTA_BASE_URL = os.getenv("PLANTA_BASE_URL", "http://sim:8100")
AUDIO_TIMEOUT_S = float(os.getenv("AUDIO_TIMEOUT_S", "60"))
AUDIO_INTENTOS = int(os.getenv("AUDIO_INTENTOS", "3"))
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")
POSTGRES_REINTENTO_S = float(os.getenv("POSTGRES_REINTENTO_S", "2"))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "4096"))
PG_TIMEOUT_S = float(os.getenv("PG_TIMEOUT_S", "5"))
INDEXAR_PG_AL_ARRANCAR = os.getenv("INDEXAR_PG_AL_ARRANCAR", "1")
CATALOGO_TIMEOUT_S = float(os.getenv("CATALOGO_TIMEOUT_S", "5"))
HISTORIAN_TIMEOUT_S = float(os.getenv("HISTORIAN_TIMEOUT_S", "5"))
HISTORIAL_TIMEOUT_S = float(os.getenv("HISTORIAL_TIMEOUT_S", "5"))
PREGUNTA_TIMEOUT_S = float(os.getenv("PREGUNTA_TIMEOUT_S", "60"))
LLM_HABILITADO = os.getenv("LLM_HABILITADO", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODELO = os.getenv("LLM_MODELO", "ministral-3:3b")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "120"))
LLM_COSTO_USD_POR_MTOK_ENTRADA = float(
    os.getenv("LLM_COSTO_USD_POR_MTOK_ENTRADA", "0")
)
LLM_COSTO_USD_POR_MTOK_SALIDA = float(
    os.getenv("LLM_COSTO_USD_POR_MTOK_SALIDA", "0")
)
TRANSCRIPCION_LIMITE_S = float(os.getenv("TRANSCRIPCION_LIMITE_S", "90"))
MAX_CORRECCIONES = int(os.getenv("MAX_CORRECCIONES", "5"))
SENSORES_HORIZONTE_HORAS = float(os.getenv("SENSORES_HORIZONTE_HORAS", "6"))
SENSORES_MAX_LECTURAS = int(os.getenv("SENSORES_MAX_LECTURAS", "500"))
SENSORES_ANOMALIA_VENTANA_MIN = float(
    os.getenv("SENSORES_ANOMALIA_VENTANA_MIN", "30")
)
SENSORES_ANOMALIA_MINIMO = int(os.getenv("SENSORES_ANOMALIA_MINIMO", "6"))
SENSORES_ANOMALIA_SPAN_MIN = float(os.getenv("SENSORES_ANOMALIA_SPAN_MIN", "10"))

MANUALES_TIMEOUT_S = float(os.getenv("MANUALES_TIMEOUT_S", "15"))
MANUALES_TEXTO_MAX = int(os.getenv("MANUALES_TEXTO_MAX", "400"))
MANUALES_TIPOS = frozenset({"manual_fabricante", "manual_operadora"})
MANUALES_DOCS = frozenset({"TX350-D", "MBP-4", "FC48-3"})

# Secciones dedicadas a modelos o plantas que no aplican a PIA-3 (Anexo,
# "trampas del corpus"). No incluye secciones mixtas como TX350-D §1.1/§2.1,
# MBP-4 §1.1/§5.3, FC48-3 §2.1 o CT-SVP-2025 §1.1: mezclan contenido valido
# con menciones a otros modelos y se devuelven completas.
MANUALES_SECCIONES_EXCLUIDAS = frozenset(
    {
        "TX350-D §3.3",
        "MBP-4 §17",
        "MBP-4 §17.1",
        "MBP-4 §17.2",
        "MBP-4 §17.3",
    }
)
