"""Indexado de fragmentos documentales para RAG (Entrega 1).

Lee fragmentos desde el simulador de planta o desde archivo local, prepara
metadatos (incluida vigencia documental) y genera estructuras listas para
cargar en pgvector. No ejecuta migraciones ni modifica la base de datos.
No copia corpus ni manuales de la academia.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fragmento:
    """Un fragmento indexable con su cita y metadatos."""

    id: str          # cita: "TX350-D §3.2", "historial OT-25-0026"
    doc: str         # id del documento: "TX350-D", "historial"
    numero: str      # numero de seccion (ej. "3.2")
    titulo: str
    texto: str
    vigente: bool    # si el documento/fragmento esta vigente
    pagina: int | None
    tipo: str        # manual, historial, contrato, certificacion
    archivo: str | None  # ruta del archivo fuente (md/pdf) en el simulador


def _vigente_por_tipo(doc: str, vigente: bool, tipo: str) -> bool:
    """Semantica de vigencia por tipo de documento.

    Los manuales (TX350-C) tienen vigente=False y se excluyen por defecto.
    Los historiales, contratos y certificaciones representan hechos pasados
    que siguen siendo relevantes, por lo que se conservan tal cual.
    """
    if tipo == "manual":
        return vigente
    return vigente


def _tipo_de_doc(doc_id: str, indice: dict[str, Any] | None) -> str:
    if indice is None:
        return "manual"
    for d in indice.get("documentos", []):
        if d.get("id") == doc_id:
            return d.get("tipo", "manual")
    return "manual"


def cargar_desde_archivo(
    ruta_fragmentos: str,
    ruta_indice: str | None = None,
) -> list[Fragmento]:
    """Carga fragmentos desde archivos locales (para pruebas sin simulador).

    No copia nada de la academia: se espera que los archivos ya esten
    disponibles en el entorno de ejecucion (por ejemplo, montados desde
    la API de la planta).
    """
    fragmentos: list[Fragmento] = []
    indice: dict[str, Any] | None = None
    if ruta_indice:
        with open(ruta_indice, encoding="utf-8") as f:
            indice = json.load(f)

    with open(ruta_fragmentos, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            datos = json.loads(linea)
            tipo = _tipo_de_doc(datos.get("doc", ""), indice)
            fragmentos.append(
                Fragmento(
                    id=datos["id"],
                    doc=datos.get("doc", ""),
                    numero=datos.get("numero", ""),
                    titulo=datos.get("titulo", ""),
                    texto=datos.get("texto", ""),
                    vigente=_vigente_por_tipo(
                        datos.get("doc", ""), bool(datos.get("vigente", True)), tipo
                    ),
                    pagina=datos.get("pagina"),
                    tipo=tipo,
                    archivo=None,
                )
            )
    return fragmentos


def cargar_desde_api(base_url: str = "http://sim:8100") -> list[Fragmento]:
    """Descarga fragmentos desde el endpoint de documentos del simulador.

    Usa /documentos/fragmentos.jsonl (archivo estatico servido por la
    planta) y /api/documentos para obtener el indice con metadatos.
    """
    fragmentos_url = base_url.rstrip("/") + "/documentos/fragmentos.jsonl"
    indice_url = base_url.rstrip("/") + "/api/documentos"

    indice: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(indice_url, timeout=5) as r:
            datos_indice = json.loads(r.read().decode("utf-8"))
            indice = {"documentos": datos_indice.get("documentos", [])}
    except Exception:
        indice = None

    with urllib.request.urlopen(fragmentos_url, timeout=10) as r:
        contenido = r.read().decode("utf-8")

    fragmentos: list[Fragmento] = []
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        datos = json.loads(linea)
        tipo = _tipo_de_doc(datos.get("doc", ""), indice)
        fragmentos.append(
            Fragmento(
                id=datos["id"],
                doc=datos.get("doc", ""),
                numero=datos.get("numero", ""),
                titulo=datos.get("titulo", ""),
                texto=datos.get("texto", ""),
                vigente=_vigente_por_tipo(
                    datos.get("doc", ""), bool(datos.get("vigente", True)), tipo
                ),
                pagina=datos.get("pagina"),
                tipo=tipo,
                archivo=None,
            )
        )
    return fragmentos


def para_pgvector(fragmentos: list[Fragmento]) -> list[dict[str, Any]]:
    """Convierte fragmentos en filas listas para INSERT en pgvector.

    No ejecuta ninguna sentencia SQL: solo prepara los diccionarios.
    La columna embedding se rellena en el paso de ingesta (despues de
    instalar las dependencias y ejecutar la migracion autorizada).
    """
    filas = []
    for f in fragmentos:
        filas.append(
            {
                "id": f.id,
                "doc": f.doc,
                "numero": f.numero,
                "titulo": f.titulo,
                "texto": f.texto,
                "vigente": f.vigente,
                "pagina": f.pagina,
                "tipo": f.tipo,
                "embedding": None,  # se rellena tras generar embeddings
            }
        )
    return filas
