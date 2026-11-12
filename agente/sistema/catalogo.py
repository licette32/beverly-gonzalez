from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import CATALOGO_TIMEOUT_S, HISTORIAN_TIMEOUT_S, PLANTA_BASE_URL
from .parte import normalizar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Equipo:
    tag: str
    tipo: str
    nombres: tuple[str, ...]
    unidad_manometro: str | None = None


class CatalogoPlanta:
    def __init__(self, equipos: list[Equipo] | None = None) -> None:
        self.equipos = equipos or []

    @classmethod
    def desde_datos(cls, datos: dict) -> CatalogoPlanta:
        equipos = []
        for equipo in datos.get("equipos", []):
            manometro = equipo.get("manometro_local") or {}
            equipos.append(
                Equipo(
                    tag=equipo["tag"],
                    tipo=equipo.get("tipo", ""),
                    nombres=tuple(equipo.get("nombres", [])),
                    unidad_manometro=manometro.get("unidad"),
                )
            )
        return cls(equipos)

    def refrescar(self) -> None:
        url = urllib.parse.urljoin(PLANTA_BASE_URL, "/api/planta")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=CATALOGO_TIMEOUT_S) as respuesta:
                datos = json.load(respuesta)
            self.equipos = self.desde_datos(datos).equipos
            log.info("catálogo de planta cargado: %s equipos", len(self.equipos))
        except Exception as exc:
            log.warning("no se pudo cargar /api/planta: %s", exc)

    def buscar_tag(self, texto: str) -> str | None:
        normalizado = normalizar(texto)
        for equipo in self.equipos:
            if re.search(rf"\b{re.escape(equipo.tag.lower())}\b", normalizado):
                return equipo.tag
        alias = [
            (normalizar(nombre), equipo.tag)
            for equipo in self.equipos
            for nombre in equipo.nombres
        ]
        alias.sort(key=lambda par: len(par[0]), reverse=True)
        for nombre, tag in alias:
            if nombre and re.search(rf"\b{re.escape(nombre)}\b", normalizado):
                return tag
        return None

    def opciones_equipo(self, tipo: str | None = None) -> list[str]:
        opciones = []
        for equipo in self.equipos:
            if tipo is not None and equipo.tipo != tipo:
                continue
            nombre = equipo.nombres[0] if equipo.nombres else equipo.tag
            opciones.append(f"{equipo.tag} ({nombre})")
        return opciones

    def unidad_manometro(self, tag: str | None) -> str | None:
        if tag is None:
            return None
        for equipo in self.equipos:
            if equipo.tag == tag:
                return equipo.unidad_manometro
        return None

    def unidades_manometro(self) -> dict[str, str]:
        return {
            equipo.tag: equipo.unidad_manometro
            for equipo in self.equipos
            if equipo.unidad_manometro
        }

    def tipo_de(self, tag: str | None) -> str | None:
        if tag is None:
            return None
        for equipo in self.equipos:
            if equipo.tag == tag:
                return equipo.tipo
        return None

    def nombre_de(self, tag: str | None) -> str | None:
        if tag is None:
            return None
        for equipo in self.equipos:
            if equipo.tag == tag:
                return equipo.nombres[0] if equipo.nombres else equipo.tag
        return None


def historian_rango(
    tag: str, variable: str, ts: datetime
) -> tuple[float, float] | None:
    """Rango histórico de las últimas 12 h. Dato adicional, nunca una decisión."""
    url = urllib.parse.urljoin(
        PLANTA_BASE_URL, f"/api/historian/{tag}/{variable}"
    )
    parametros = urllib.parse.urlencode(
        {
            "desde": (ts - timedelta(hours=12)).isoformat(),
            "hasta": ts.isoformat(),
        }
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{url}?{parametros}", timeout=HISTORIAN_TIMEOUT_S) as respuesta:
            datos = json.load(respuesta)
        valores = [fila["valor"] for fila in datos if fila.get("valor") is not None]
        if not valores:
            return None
        return min(valores), max(valores)
    except Exception as exc:
        log.warning("no se pudo leer historian %s/%s: %s", tag, variable, exc)
        return None
