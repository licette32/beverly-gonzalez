import os

MQTT_HOST = os.getenv("MQTT_HOST", "broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
SISTEMA = os.getenv("SISTEMA_NOMBRE", "pia3-agente-planta")
HEARTBEAT_S = int(os.getenv("HEARTBEAT_S", "30"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PLANTA_BASE_URL = os.getenv("PLANTA_BASE_URL", "http://sim:8100")
AUDIO_TIMEOUT_S = float(os.getenv("AUDIO_TIMEOUT_S", "60"))
AUDIO_INTENTOS = int(os.getenv("AUDIO_INTENTOS", "3"))
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")
POSTGRES_REINTENTO_S = float(os.getenv("POSTGRES_REINTENTO_S", "2"))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "4096"))
PG_TIMEOUT_S = float(os.getenv("PG_TIMEOUT_S", "5"))
CATALOGO_TIMEOUT_S = float(os.getenv("CATALOGO_TIMEOUT_S", "5"))
HISTORIAN_TIMEOUT_S = float(os.getenv("HISTORIAN_TIMEOUT_S", "5"))
PREGUNTA_TIMEOUT_S = float(os.getenv("PREGUNTA_TIMEOUT_S", "60"))
TRANSCRIPCION_LIMITE_S = float(os.getenv("TRANSCRIPCION_LIMITE_S", "90"))
MAX_CORRECCIONES = int(os.getenv("MAX_CORRECCIONES", "5"))

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
