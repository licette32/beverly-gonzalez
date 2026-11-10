import os

MQTT_HOST = os.getenv("MQTT_HOST", "broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
SISTEMA = os.getenv("SISTEMA_NOMBRE", "pia3-agente-planta")
HEARTBEAT_S = int(os.getenv("HEARTBEAT_S", "30"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
