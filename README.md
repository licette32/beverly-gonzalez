# Agente Beverly González

Esqueleto de la Entrega 1 del TP de Academia Novit 2026.

## Estado actual

- Se conecta al broker MQTT de la planta.
- Valida los mensajes entrantes con `planta_contrato`.
- Publica `sistema/estado` cada 30 segundos desde un hilo independiente.
- Todavía no transcribe audio, no detecta fallas y no genera partes.

## Requisitos

- Docker Desktop.
- Red externa `planta-lan`.
- Planta de desarrollo levantada desde `academia2026-tp`.

## Ejecutar

```bash
docker compose up -d --build
docker compose logs -f agente
```

## Variables

Copiar `.env.example` a `.env` si hace falta cambiar el host, el puerto, el intervalo del latido o el proxy.

## Pruebas

```bash
python -m unittest discover -s tests -v
```
