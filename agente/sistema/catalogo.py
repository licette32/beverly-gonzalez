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

ESTADOS_EXCLUIDOS = frozenset({"parada", "mantenimiento"})


@dataclass(frozen=True)
class Equipo:
    tag: str
    tipo: str
    nombres: tuple[str, ...]
    unidad_manometro: str | None = None


class CatalogoPlanta:
    def __init__(
        self,
        equipos: list[Equipo] | None = None,
        limites: dict[tuple[str, str], dict[str, float]] | None = None,
    ) -> None:
        self.equipos = equipos or []
        self.limites = limites or {}

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
        limites = {}
        for sensor in datos.get("sensores", []):
            valores = {
                clave: float(sensor[clave])
                for clave in ("alarma_alta", "alarma_baja")
                if sensor.get(clave) is not None
            }
            if valores:
                limites[(sensor["tag"], sensor["variable"])] = valores
        return cls(equipos, limites)

    def refrescar(self) -> None:
        url = urllib.parse.urljoin(PLANTA_BASE_URL, "/api/planta")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=CATALOGO_TIMEOUT_S) as respuesta:
                datos = json.load(respuesta)
            nuevo = self.desde_datos(datos)
            self.equipos = nuevo.equipos
            self.limites.clear()
            self.limites.update(nuevo.limites)
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


class EstadoPlanta:
    def __init__(self) -> None:
        self._excluidos: frozenset[str] | None = None

    def ultimo(self) -> frozenset[str] | None:
        return self._excluidos

    def excluidos(self) -> frozenset[str] | None:
        url = urllib.parse.urljoin(PLANTA_BASE_URL, "/api/estado")
        try:
            datos = self._leer(url)
            self._excluidos = self.desde_datos(datos)
        except Exception as exc:
            if self._excluidos is None:
                log.warning(
                    "no se pudo leer /api/estado y no hay estado previo: %s", exc
                )
            else:
                log.warning(
                    "no se pudo leer /api/estado; se usa el último estado: %s", exc
                )
        return self._excluidos

    @staticmethod
    def desde_datos(datos: dict) -> frozenset[str]:
        excluidos = {
            bomba["tag"]
            for bomba in datos.get("bombas", [])
            if bomba.get("tag") and bomba.get("estado") in ESTADOS_EXCLUIDOS
        }
        excluidos.update(
            filtro["tag"]
            for filtro in datos.get("filtros", [])
            if filtro.get("tag") and filtro.get("en_cambio") is True
        )
        return frozenset(excluidos)

    @staticmethod
    def _leer(url: str) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=CATALOGO_TIMEOUT_S) as respuesta:
            return json.load(respuesta)


def historian_rango(
    tag: str, variable: str, ts: datetime
) -> tuple[float, float] | None:
    """Rango histórico de las últimas 12 h. Dato adicional, nunca una decisión."""
    url = urllib.parse.urljoin(
        PLANTA_BASE_URL, f"/api/historian/{tag}/{variable}"
    )
    parametros = urllib.parse.urlencode(
        {
            "desde": (ts - timedelta(days=45)).isoformat(),
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
