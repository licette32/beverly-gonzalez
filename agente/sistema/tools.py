from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, List, Literal, Optional

import yaml

from pydantic import BaseModel, Field, ValidationError
from pydantic.config import ConfigDict

# Exposed for testing (can be patched with unittest.mock)
PLANTA_BASE_URL = os.getenv("PLANTA_BASE_URL", "http://sim:8100")
MATERIALES_PATH = os.path.join(os.path.dirname(__file__), "..", "datos", "materiales.yaml")

from .config import (
    CATALOGO_TIMEOUT_S,
    ESPERA_REINTENTO_TOOL_S,
    HISTORIAL_TIMEOUT_S,
    HISTORIAN_TIMEOUT_S,
    MANUALES_DOCS,
    MANUALES_SECCIONES_EXCLUIDAS,
    MANUALES_TEXTO_MAX,
    MANUALES_TIMEOUT_S,
    MANUALES_TIPOS,
    PREGUNTA_TIMEOUT_S,
    REINTENTOS_TOOL_LECTURA,
)
from .repositorio_decisiones import (
    MODELO_CONTROL,
    RegistroDecisiones,
    argumentos_catalogo,
    argumentos_historial_ordenes,
    argumentos_historian,
    argumentos_manuales_buscar,
    registrar_directo,
)


class ErrorInfo(Exception):
    """Error con estructura {codigo, mensaje, reintentable}."""

    def __init__(self, codigo: str, mensaje: str, reintentable: bool = False) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.reintentable = reintentable


def _clasificar_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, urllib.error.HTTPError):
        return f"API_HTTP_{exc.code}", 500 <= exc.code < 600
    if isinstance(exc, json.JSONDecodeError):
        return "API_PARSE", False
    if isinstance(exc, TimeoutError):
        return "API_TIMEOUT", True
    if isinstance(exc, ConnectionError):
        return "API_CONEXION", True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "API_TIMEOUT", True
        return "API_CONEXION", True
    return "API_ERROR", False


def _registrar_intento(
    nombre: str,
    registro: RegistroDecisiones | None,
    correlation_id: str | None,
    argumentos: Any,
    resultado: str,
    intento: int,
    codigo: str | None = None,
) -> None:
    datos = dict(argumentos or {})
    datos["resultado"] = resultado
    datos["intento"] = intento
    if codigo is not None:
        datos["codigo"] = codigo
    registrar_directo(
        registro,
        correlation_id=correlation_id or nombre,
        paso=f"tool:{nombre}",
        modelo=MODELO_CONTROL,
        herramienta=nombre,
        argumentos=datos,
    )


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
    codigo: str
    nombre: str
    unidad: str
    almacen: Literal["yacimiento", "central"]
    cantidad: float
    costo_unitario: float


class _TareaEstandar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str
    nombre: str
    equipos: List[str]
    detiene: bool
    horas: float
    ejecutor: str
    repuestos: List[dict[str, Any]]


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


class ManualEncontrado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cita: str
    documento: str
    seccion: str
    texto: str
    vigente: bool


def _url(path: str) -> str:
    return urllib.parse.urljoin(PLANTA_BASE_URL, path)


def _opener(timeout: float):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fetch(
    url: str,
    timeout: float,
    *,
    nombre: str = "api",
    registro: RegistroDecisiones | None = None,
    correlation_id: str | None = None,
    argumentos: Any = None,
) -> dict[str, Any]:
    intentos = max(1, REINTENTOS_TOOL_LECTURA)
    for intento in range(1, intentos + 1):
        try:
            with _opener(timeout).open(url, timeout=timeout) as respuesta:
                datos = json.load(respuesta)
            _registrar_intento(
                nombre, registro, correlation_id, argumentos, "ok", intento
            )
            return datos
        except Exception as exc:
            codigo, reintentable = _clasificar_error(exc)
            if reintentable and intento < intentos:
                _registrar_intento(
                    nombre, registro, correlation_id, argumentos, "reintento", intento, codigo
                )
                if ESPERA_REINTENTO_TOOL_S > 0:
                    time.sleep(ESPERA_REINTENTO_TOOL_S)
                continue
            _registrar_intento(
                nombre, registro, correlation_id, argumentos, "error", intento, codigo
            )
            raise ErrorInfo(codigo=codigo, mensaje=str(exc), reintentable=False) from exc
    raise ErrorInfo(codigo="API_ERROR", mensaje="sin intentos", reintentable=False)


def historian(
    tag: str,
    variable: str,
    desde: str | None = None,
    hasta: str | None = None,
    *,
    registro: RegistroDecisiones | None = None,
    correlation_id: str | None = None,
) -> HistorianResponse:
    query = urllib.parse.urlencode({"desde": desde or "", "hasta": hasta or ""})
    url = _url(f"/api/historian/{tag}/{variable}?{query}")
    try:
        data = _fetch(
            url,
            HISTORIAN_TIMEOUT_S,
            nombre="historian",
            registro=registro,
            correlation_id=correlation_id,
            argumentos=argumentos_historian(tag, variable, desde, hasta),
        )
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
        raise ErrorInfo(codigo="HISTORIAN_ERROR", mensaje=str(exc), reintentable=False) from exc


def catalogo(
    tag: str | None = None,
    *,
    registro: RegistroDecisiones | None = None,
    correlation_id: str | None = None,
) -> CatalogoResponse:
    url = _url("/api/planta")
    try:
        data = _fetch(
            url,
            CATALOGO_TIMEOUT_S,
            nombre="catalogo",
            registro=registro,
            correlation_id=correlation_id,
            argumentos=argumentos_catalogo(tag),
        )
        equipos = data.get("equipos", [])
        if tag:
            equipos = [e for e in equipos if e.get("tag") == tag]
        return CatalogoResponse(equipos=equipos)
    except ErrorInfo:
        raise
    except Exception as exc:
        raise ErrorInfo(codigo="CATALOGO_ERROR", mensaje=str(exc), reintentable=False) from exc


def historial_ordenes(
    equipo: str,
    orden_id: str | None = None,
    *,
    registro: RegistroDecisiones | None = None,
    correlation_id: str | None = None,
) -> HistorialOrdenesResponse:
    """Órdenes históricas de un equipo; el filtro por id se hace localmente.

    La API de la planta devuelve la lista de órdenes del archivo más las del
    precalentamiento del escenario. El filtro por ``orden_id`` se aplica acá
    para no depender de que el endpoint lo soporte.
    """
    query = urllib.parse.urlencode({"equipo": equipo})
    url = _url(f"/api/historial-ordenes?{query}")
    try:
        data = _fetch(
            url,
            HISTORIAL_TIMEOUT_S,
            nombre="historial_ordenes",
            registro=registro,
            correlation_id=correlation_id,
            argumentos=argumentos_historial_ordenes(equipo, orden_id),
        )
        ordenes = data if isinstance(data, list) else data.get("ordenes", [])
        if not isinstance(ordenes, list):
            ordenes = []
        if orden_id:
            ordenes = [o for o in ordenes if isinstance(o, dict) and o.get("id") == orden_id]
        return HistorialOrdenesResponse.model_validate({"ordenes": ordenes})
    except ErrorInfo:
        raise
    except Exception as exc:
        raise ErrorInfo(
            codigo="HISTORIAL_ORDENES_ERROR", mensaje=str(exc), reintentable=False
        ) from exc


def _cargar_materiales() -> dict[str, Any]:
    try:
        with open(MATERIALES_PATH, encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise ErrorInfo(
            codigo="MATERIALES_ARCHIVO_AUSENTE",
            mensaje=f"no existe {MATERIALES_PATH}",
            reintentable=False,
        ) from exc
    except UnicodeDecodeError as exc:
        raise ErrorInfo(
            codigo="MATERIALES_YAML_INVALIDO",
            mensaje=str(exc),
            reintentable=False,
        ) from exc
    except OSError as exc:
        raise ErrorInfo(
            codigo="MATERIALES_NO_DISPONIBLE",
            mensaje=str(exc),
            reintentable=False,
        ) from exc
    except yaml.YAMLError as exc:
        raise ErrorInfo(
            codigo="MATERIALES_YAML_INVALIDO",
            mensaje=str(exc),
            reintentable=False,
        ) from exc
    if not isinstance(datos, dict):
        raise ErrorInfo(
            codigo="MATERIALES_ESQUEMA_INVALIDO",
            mensaje="el archivo no contiene un objeto YAML",
            reintentable=False,
        )
    return datos


def _items_de_stock(repuestos: list[dict[str, Any]]) -> list[StockItem]:
    items: list[StockItem] = []
    for i, repuesto in enumerate(repuestos):
        try:
            stock = repuesto["stock"]
            for almacen in ("yacimiento", "central"):
                items.append(
                    StockItem(
                        codigo=repuesto["codigo"],
                        nombre=repuesto["nombre"],
                        unidad=repuesto["unidad"],
                        almacen=almacen,
                        cantidad=stock[almacen],
                        costo_unitario=repuesto["costo_usd"],
                    )
                )
        except (KeyError, TypeError, ValidationError) as exc:
            raise ErrorInfo(
                codigo="MATERIALES_ESQUEMA_INVALIDO",
                mensaje=f"repuestos[{i}]: {exc}",
                reintentable=False,
            ) from exc
    return items


def stock(tag: str | None = None) -> StockResponse:
    """Stock desde agente/datos/materiales.yaml, una fila por repuesto y almacén.

    Si tag no tiene repuestos en lista_materiales, devuelve vacío válido.
    """
    datos = _cargar_materiales()
    repuestos = datos.get("repuestos")
    if not isinstance(repuestos, list):
        raise ErrorInfo(
            codigo="MATERIALES_ESQUEMA_INVALIDO",
            mensaje="repuestos debe ser una lista",
            reintentable=False,
        )
    items = _items_de_stock(repuestos)
    if tag:
        lista_materiales = datos.get("lista_materiales")
        if not isinstance(lista_materiales, dict):
            raise ErrorInfo(
                codigo="MATERIALES_ESQUEMA_INVALIDO",
                mensaje="lista_materiales debe ser un objeto",
                reintentable=False,
            )
        codigos = lista_materiales.get(tag, [])
        if not isinstance(codigos, list) or not all(isinstance(c, str) for c in codigos):
            raise ErrorInfo(
                codigo="MATERIALES_ESQUEMA_INVALIDO",
                mensaje=f"lista_materiales[{tag!r}] debe ser una lista de códigos",
                reintentable=False,
            )
        items = [item for item in items if item.codigo in codigos]
    return StockResponse(items=items, vacio=not items)


def tareas_catalogo() -> List[dict[str, Any]]:
    """Catálogo de tareas estándar desde agente/datos/materiales.yaml.

    No incluye tareas_no_estandar.
    """
    datos = _cargar_materiales()
    tareas = datos.get("tareas_estandar")
    if not isinstance(tareas, list):
        raise ErrorInfo(
            codigo="MATERIALES_ESQUEMA_INVALIDO",
            mensaje="tareas_estandar debe ser una lista",
            reintentable=False,
        )
    for i, tarea in enumerate(tareas):
        try:
            _TareaEstandar.model_validate(tarea)
        except ValidationError as exc:
            raise ErrorInfo(
                codigo="MATERIALES_ESQUEMA_INVALIDO",
                mensaje=f"tareas_estandar[{i}]: {exc}",
                reintentable=False,
            ) from exc
    return tareas


def _buscar_manuales_en_hilo(texto: str) -> list[str]:
    """Ejecuta rag.buscar en un hilo daemon y corta a los MANUALES_TIMEOUT_S."""
    from . import rag

    resultado: dict[str, Any] = {}

    def objetivo() -> None:
        try:
            resultado["citas"] = rag.buscar(texto, k=5)
        except BaseException as exc:  # noqa: BLE001
            resultado["error"] = exc

    hilo = threading.Thread(target=objetivo, name="manuales-buscar", daemon=True)
    hilo.start()
    hilo.join(MANUALES_TIMEOUT_S)
    if hilo.is_alive():
        raise ErrorInfo(
            codigo="MANUALES_TIMEOUT",
            mensaje=f"búsqueda de manuales superó {MANUALES_TIMEOUT_S} s",
            reintentable=True,
        )
    if "error" in resultado:
        raise ErrorInfo(
            codigo="MANUALES_ERROR",
            mensaje=str(resultado["error"]),
            reintentable=True,
        )
    return resultado.get("citas") or []


def _fragmentos_manuales() -> dict[str, Any]:
    from . import rag

    try:
        return rag._obtener_retriever().por_id
    except Exception as exc:
        raise ErrorInfo(
            codigo="MANUALES_ERROR", mensaje=str(exc), reintentable=True
        )


def _manuales_una_vez(texto: str) -> List[ManualEncontrado]:
    citas = _buscar_manuales_en_hilo(texto)
    por_id = _fragmentos_manuales()
    encontrados: List[ManualEncontrado] = []
    for cita in citas:
        fragmento = por_id.get(cita)
        if fragmento is None:
            continue
        if not fragmento.vigente:
            continue
        if fragmento.tipo not in MANUALES_TIPOS:
            continue
        if fragmento.doc not in MANUALES_DOCS:
            continue
        if fragmento.id in MANUALES_SECCIONES_EXCLUIDAS:
            continue
        encontrados.append(
            ManualEncontrado(
                cita=fragmento.id,
                documento=fragmento.doc,
                seccion=fragmento.numero,
                texto=fragmento.texto[:MANUALES_TEXTO_MAX],
                vigente=bool(fragmento.vigente),
            )
        )
    return encontrados


def manuales_buscar(
    texto: str,
    *,
    registro: RegistroDecisiones | None = None,
    correlation_id: str | None = None,
) -> List[ManualEncontrado]:
    """Busca en manuales vigentes de PIA-3, con timeout y un reintento."""
    if not texto or not texto.strip():
        return []
    base = argumentos_manuales_buscar(texto)
    for intento in range(1, 3):
        try:
            encontrados = _manuales_una_vez(texto)
        except ErrorInfo as exc:
            if intento == 1 and exc.reintentable:
                _registrar_intento(
                    "manuales_buscar",
                    registro,
                    correlation_id,
                    base,
                    "reintento",
                    intento,
                    exc.codigo,
                )
                continue
            _registrar_intento(
                "manuales_buscar",
                registro,
                correlation_id,
                base,
                "error",
                intento,
                exc.codigo,
            )
            raise ErrorInfo(
                codigo=exc.codigo, mensaje=exc.mensaje, reintentable=False
            ) from exc
        _registrar_intento(
            "manuales_buscar", registro, correlation_id, base, "ok", intento
        )
        return encontrados
    raise ErrorInfo(codigo="MANUALES_ERROR", mensaje="sin intentos", reintentable=False)