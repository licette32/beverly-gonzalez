from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pia3-planta")


@mcp.tool()
def equipos() -> list[str]:
    """Lista de equipos de la planta."""
    from .catalogo import CatalogoPlanta
    catalogo = CatalogoPlanta()
    catalogo.refrescar()
    return catalogo.opciones_equipo()


@mcp.tool()
def historian(tag: str, variable: str, desde: str | None = None, hasta: str | None = None) -> list[float]:
    """Rango histórico de valores para una variable de un equipo."""
    from .tools import historian
    from .config import HISTORIAN_TIMEOUT_S
    from dataclasses import dataclass

    @dataclass
    class Respuesta:
        valores: list[float] | None = None

    try:
        resp = historian(tag, variable, desde, hasta)
        return resp.valores or []
    except Exception:
        return []


@mcp.tool()
def catalogo_planta(tag: str | None = None) -> list[dict]:
    """Catálogo completo de equipos de planta."""
    from .catalogo import CatalogoPlanta
    catalogo = CatalogoPlanta.desde_datos({})
    return catalogo.equipos


@mcp.tool()
def stock(tag: str | None = None) -> list[dict]:
    """Stock actual de equipos."""
    from .tools import stock
    try:
        resp = stock(tag)
        return [{"tag": i.tag, "nombre": i.nombre, "cantidad": i.cantidad, "unidad": i.unidad} for i in resp.items]
    except Exception:
        return []


@mcp.tool()
def historial_ordenes(tag: str | None = None, orden_id: str | None = None) -> list[dict]:
    """Historial de órdenes de trabajo."""
    from .tools import tareas_catalogo
    try:
        tareas = tareas_catalogo()
        if tag:
            tareas = [t for t in tareas if t.get("tag") == tag]
        if orden_id:
            tareas = [t for t in tareas if t.get("id") == orden_id]
        return tareas
    except Exception:
        return []


@mcp.tool()
def manuales_buscar(texto: str) -> list[dict]:
    """Busca en los manuales vigentes de la planta."""
    from .tools import manuales_buscar as buscar
    try:
        return [encontrado.model_dump() for encontrado in buscar(texto)]
    except Exception:
        return []


if __name__ == "__main__":
    mcp.run(transport="stdio")