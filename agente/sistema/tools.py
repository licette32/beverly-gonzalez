from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Optional, List

import yaml

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

# Exposed for testing (can be patched with unittest.mock)
PLANTA_BASE_URL = os.getenv("PLANTA_BASE_URL", "http://sim:8100")

from .config import CATALOGO_TIMEOUT_S, HISTORIAN_TIMEOUT_S, PREGUNTA_TIMEOUT_S


class ErrorInfo(Exception):
    """Error con estructura {codigo, mensaje, reintentable}."""

    def __init__(self, codigo: str, mensaje: str, reintentable: bool = False) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.reintentable = reintentable


class HistorianRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    variable: str
    desde: Optional[str] = Field(default=None, description="Fecha/hora inicio (ISO)")
    hasta: Optional[str] = Field(default=None, description="Fecha/hora fin (ISO)")


class HistorianResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    variable: str
    valores: List[float] = Field(default_factory=list)
    ts_inicio: Optional[str] = Field(default=None)
    ts_fin: Optional[str] = Field(default=None)


class CatalogoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: Optional[str] = Field(default=None)


class CatalogoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipos: List[dict[str, Any]] = Field(default_factory=list)


class StockItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    nombre: str
    cantidad: float
    unidad: str


class StockQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: Optional[str] = Field(default=None)


class StockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[StockItem] = Field(default_factory=list)
    vacio: bool = True


class HistorialOrdenesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    orden_id: Optional[str] = Field(default=None)


class HistorialOrdenesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordenes: List[dict[str, Any]] = Field(default_factory=list)


def _url(path: str) -> str:
    return urllib.parse.urljoin(PLANTA_BASE_URL, path)


def _opener(timeout: float):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fetch(url: str, timeout: float) -> dict[str, Any]:
    try:
        with _opener(timeout).open(url, timeout=timeout) as respuesta:
            return json.load(respuesta)
    except Exception as exc:
        raise ErrorInfo(codigo="API_ERROR", mensaje=str(exc), reintentable=True)


def historian(tag: str, variable: str, desde: str | None = None, hasta: str | None = None) -> HistorianResponse:
    query = urllib.parse.urlencode({"desde": desde or "", "hasta": hasta or ""})
    url = _url(f"/api/historian/{tag}/{variable}?{query}")
    try:
        data = _fetch(url, HISTORIAN_TIMEOUT_S)
        valores = [fila["valor"] for fila in data if fila.get("valor") is not None]
        return HistorianResponse(
            tag=tag,
            variable=variable,
            valores=valores,
            ts_inicio=desde,
            ts_fin=hasta,
        )
    except ErrorInfo:
        raise
    except Exception as exc:
        raise ErrorInfo(codigo="HISTORIAN_ERROR", mensaje=str(exc), reintentable=True)


def catalogo(tag: str | None = None) -> CatalogoResponse:
    url = _url("/api/planta")
    try:
        data = _fetch(url, CATALOGO_TIMEOUT_S)
        equipos = data.get("equipos", [])
        if tag:
            equipos = [e for e in equipos if e.get("tag") == tag]
        return CatalogoResponse(equipos=equipos)
    except ErrorInfo:
        raise
    except Exception as exc:
        raise ErrorInfo(codigo="CATALOGO_ERROR", mensaje=str(exc), reintentable=True)


def stock(tag: str | None = None) -> StockResponse:
    """Stock desde YAML propio en agente/datos/stock.yaml. Si no existe, vacío documentado."""
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "datos", "stock.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path) as f:
            datos = yaml.safe_load(f) or {}
        items = datos.get("stock", [])
        if tag:
            items = [i for i in items if i.get("tag") == tag]
        return StockResponse(items=[StockItem(**i) for i in items], vacio=False)
    return StockResponse(items=[], vacio=True)


def tareas_catalogo() -> List[dict[str, Any]]:
    """Catálogo de tareas desde YAML propio en agente/datos/tareas.yaml."""
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "datos", "tareas.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path) as f:
            datos = yaml.safe_load(f) or {}
        return datos.get("tareas", [])
    return []


def manuales_buscar(texto: str) -> List[dict[str, Any]]:
    """Búsqueda en manuales: vacía y documentada como diferida."""
    return []