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
    """Stock actual de repuestos por almacén."""
    from .tools import stock
    resp = stock(tag)
    return [item.model_dump() for item in resp.items]


@mcp.tool()
def tareas_catalogo(equipo: str | None = None, codigo: str | None = None) -> list[dict]:
    """Catálogo de tareas estándar de mantenimiento."""
    from .tools import tareas_catalogo as catalogo
    tareas = catalogo()
    if equipo:
        tareas = [t for t in tareas if equipo in t.get("equipos", [])]
    if codigo:
        tareas = [t for t in tareas if t.get("codigo") == codigo]
    return tareas


@mcp.tool()
def historial_ordenes(equipo: str, orden_id: str | None = None) -> list[dict]:
    """Órdenes históricas de un equipo, opcionalmente filtradas por id."""
    from .tools import historial_ordenes as buscar
    try:
        resp = buscar(equipo, orden_id)
        return list(resp.ordenes)
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