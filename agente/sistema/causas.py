# Fuente: novit-curso docs/fallas.md y MBP-4 §6. Cada fila cita su sección.
FALLAS = {
    "F01": dict(nombre="Pérdida por empaquetadura", fab="TX-T01", equipos="bombas",
                tarea="T-B-EMP", ejecutor="propio",
                firma_sensores=["caudal_baja_leve"],
                firma_recorrida=["goteo_prensaestopas_crece", "foto_empaquetadura"],
                cita=("MBP-4", "6.3")),
    "F02": dict(nombre="Válvulas de succión/descarga gastadas", fab="TX-T02", equipos="bombas",
                tarea="T-B-VAL", ejecutor="propio",
                firma_sensores=["vibracion_sube", "pulsacion_descarga_sube", "caudal_baja"],
                firma_recorrida=["golpeteo_metalico", "aguja_manometro_oscila"],
                cita=("MBP-4", "6.4")),
    "F03": dict(nombre="Rodamiento de cigüeñal dañado", fab="TX-T03", equipos="bombas",
                tarea="T-B-ROD", ejecutor="contratista (Servipat)",
                firma_sensores=["vibracion_acelera", "temp_aceite_sube"],
                firma_recorrida=["zumbido_rodamiento", "temp_rodamiento_alta_ir"],
                cita=("MBP-4", "6.5")),
    "F04": dict(nombre="Bajo nivel de aceite del cárter", fab="TX-T04", equipos="bombas",
                tarea="T-B-ACE", ejecutor="propio",
                firma_sensores=["temp_aceite_sube_gradual", "vibracion_sin_cambio"],
                firma_recorrida=["visor_aceite_bajo"],
                cita=("MBP-4", "6.6")),
    "F05": dict(nombre="Correas flojas o gastadas", fab="TX-T05", equipos="bombas",
                tarea="T-B-COR", ejecutor="propio",
                firma_sensores=["caudal_baja", "succion_normal"],
                firma_recorrida=["chirrido", "polea_motor_calientes", "correas_brillantes", "foto_correas"],
                cita=("MBP-4", "6.7")),
    "F06": dict(nombre="Acople desalineado / elastómero gastado", fab="TX-T06", equipos="bombas",
                tarea="T-B-ALI", ejecutor="contratista (Servipat)",
                firma_sensores=["vibracion_moderada_sube", "sin_pulsacion_descarga"],
                firma_recorrida=["acople_caliente_ir", "polvo_elastomero", "foto_acople"],
                cita=("MBP-4", "6.8")),
    "F07": dict(nombre="Cartuchos colmatados", fab="FC-T01", equipos="filtros",
                tarea="T-F-CAR", ejecutor="propio",
                firma_sensores=["dp_filtro_sube", "succion_todas_bombas_baja"],
                firma_recorrida=["manometro_diferencial_alto"],
                cita=("MBP-4", "6.9")),
    "F08": dict(nombre="Cartucho roto (agua sin filtrar)", fab="FC-T02", equipos="filtros",
                tarea="T-F-CAR", ejecutor="propio",   # "+ inspección": la fuente no dice cuál
                firma_sensores=["dp_filtro_cae_de_golpe_bajo_alarma"],
                firma_recorrida=[],
                cita=("MBP-4", "6.10")),
    "F09": dict(nombre="Cavitación por baja succión", fab="TX-T07", equipos="bombas",
                tarea=None,  # va al equipo raíz: filtro (F07 -> T-F-CAR) o TK-301
                ejecutor="propio",
                firma_sensores=["succion_baja", "vibracion_sube", "caudal_baja"],
                firma_recorrida=["ruido_a_piedras"],
                causa_raiz_en_otro_equipo=True,
                cita=("MBP-4", "6.11")),
    "F10": dict(nombre="Sensor congelado o con deriva", fab="TX-T08 / FC-T04", equipos="cualquier sensor",
                tarea="T-I-CAL", ejecutor="propio",
                firma_sensores=["valor_plano_sin_ruido", "deriva_sin_cambio_en_relacionadas"],
                firma_recorrida=["lectura_local_no_coincide"],
                genera_orden_por_defecto=False,   # issue 6: "F10 no exige orden"
                cita=("MBP-4", "6.12")),
}
# Reglas de ordenamiento por ambigüedad (de la matriz de firmas 6.2):
#  vibración ↑ + pulsación descarga ↑ -> F02 ; vibración ↑ moderada sin pulsación -> F06 ;
#  vibración ↑ acelerando + temp aceite ↑ -> F03 ; succión ↓ + vibración ↑ -> F09 ;
#  temp aceite ↑ gradual sin vibración -> F04 ; caudal ↓ con succión normal -> F05 ; caudal ↓ leve -> F01.
# Cadenas (6.13): F07 severa -> F09 ; F08 -> F02 en bombas en marcha.

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Sequence

from planta_contrato import FilaParte

from . import tools
from .config import MANUALES_DOCS, MANUALES_TIPOS
from .parte import A_KG, LIMITES, ItemParte, normalizar
from .tools import ManualEncontrado, manuales_buscar


@dataclass(frozen=True)
class Anomalia:
    tag: str
    variable: str
    ts: datetime
    lado: Literal["alta", "baja"] | None = None


BOMBAS = ("B-101", "B-102", "B-103")
FILTROS = ("F-201A", "F-201B")
EQUIPOS_RELACIONADOS = (*FILTROS, *BOMBAS)
CAUDALIMETRO = "FT-401"
TANQUE = "TK-301"

INSPECCIONES = {"I-VIB": "contratista", "I-VAL": "propio"}
NEGATIVAS = frozenset(
    {"vibracion_sin_cambio", "succion_normal", "sin_pulsacion_descarga"}
)
OBS_ACEITE_BAJO = frozenset({"nivel de aceite bajo"})
OBS_GOTEO = frozenset(
    {"goteo por empaquetadura", "perdida importante por empaquetadura"}
)
OBS_RODAMIENTO_CALIENTE = frozenset({"rodamiento caliente"})
DP_ALARMA_ALTA = LIMITES[("F-201A", "presion_diferencial")]["alarma_alta"]
# planta.yaml: F-201A/B presion_diferencial alarma_alta=1.5 (vía parte.LIMITES).
UMBRAL_RODAMIENTO_IR = 75.0
# parte.py:318 e interpretacion.py:22: "rodamiento caliente" si valor > 75 °C.
OBS_PULSACION = frozenset(
    {
        "pulsacion de descarga",
        "pulsacion descarga",
        "aguja oscila",
        "aguja de descarga oscila",
        "aguja del manometro oscila",
    }
)
OBS_LECTURA_LOCAL = frozenset(
    {"lectura local no coincide", "lectura local distinta"}
)


@dataclass(frozen=True)
class EvidenciaEquipo:
    equipo: str
    desde: datetime
    hasta: datetime
    anomalias: tuple[Anomalia, ...] = ()
    partes: tuple[ItemParte | FilaParte, ...] = ()

    @staticmethod
    def _observacion(parte: ItemParte | FilaParte) -> str:
        return normalizar(parte.observacion or "")

    def activa(
        self,
        tag: str,
        variable: str,
        lado: Literal["alta", "baja"] | None = None,
    ) -> bool:
        for anomalia in self.anomalias:
            if anomalia.tag != tag or anomalia.variable != variable:
                continue
            if not self.desde <= anomalia.ts <= self.hasta:
                continue
            if (
                lado is not None
                and anomalia.lado is not None
                and anomalia.lado != lado
            ):
                continue
            return True
        return False

    def ausente(self, tag: str, variable: str) -> bool:
        return not self.activa(tag, variable)

    def firma_recorrida(self, firma: str, tag: str | None = None) -> bool:
        if firma == "aguja_manometro_oscila":
            observaciones = OBS_PULSACION
            variable = "presion_descarga_local"
        elif firma == "lectura_local_no_coincide":
            observaciones = OBS_LECTURA_LOCAL
            variable = None
        elif firma == "goteo_prensaestopas_crece":
            observaciones, variable = OBS_GOTEO, "goteo_empaquetadura"
        elif firma == "golpeteo_metalico":
            observaciones, variable = frozenset({"golpeteo metalico"}), "ruido"
        elif firma == "zumbido_rodamiento":
            observaciones, variable = frozenset({"ruido de rodamiento"}), "ruido"
        elif firma == "temp_rodamiento_alta_ir":
            observaciones, variable = OBS_RODAMIENTO_CALIENTE, "temperatura_rodamiento_ir"
        elif firma == "visor_aceite_bajo":
            observaciones, variable = OBS_ACEITE_BAJO, "nivel_aceite_visor"
        elif firma == "manometro_diferencial_alto":
            observaciones, variable = frozenset({"diferencial alto"}), "presion_diferencial"
        elif firma == "ruido_a_piedras":
            observaciones, variable = frozenset({"cavitacion"}), "ruido"
        else:
            return False
        for parte in self.partes:
            if tag is not None and parte.tag != tag:
                continue
            if variable is not None and parte.variable != variable:
                continue
            if self._observacion(parte) in observaciones:
                return True
            if (
                variable == "presion_diferencial"
                and parte.valor is not None
                and parte.valor * A_KG.get(parte.unidad or "kg/cm2", 1.0)
                >= DP_ALARMA_ALTA
            ):
                return True
            if (
                variable == "temperatura_rodamiento_ir"
                and parte.valor is not None
                and parte.valor > UMBRAL_RODAMIENTO_IR
            ):
                return True
        return False


@dataclass(frozen=True)
class Causa:
    codigo_falla: str
    descripcion: str
    evidencia: tuple[str, ...]
    faltantes: tuple[str, ...]
    tarea_codigo: str | None
    equipo_orden: str
    citas: tuple[str, ...]
    accion: str
    genera_orden: bool
    ejecutor: str
    antecedentes: tuple[str, ...] = ()


def lado_desde_limite(limite_violado: str | None) -> Literal["alta", "baja"] | None:
    """Traduce ``Resultado.limite_violado``; sin coincidencia exacta no inventa lado."""
    if not limite_violado:
        return None
    alta = "alarma_alta" in limite_violado
    baja = "alarma_baja" in limite_violado
    if alta == baja:
        return None
    return "alta" if alta else "baja"


def _primer_filtro(
    evidencia: EvidenciaEquipo, lado: Literal["alta", "baja"]
) -> str | None:
    return next(
        (
            anomalia.tag
            for anomalia in evidencia.anomalias
            if anomalia.tag in FILTROS
            and anomalia.variable == "presion_diferencial"
            and anomalia.lado == lado
            and evidencia.desde <= anomalia.ts <= evidencia.hasta
        ),
        None,
    )


def _firmas_presentes(evidencia: EvidenciaEquipo) -> frozenset[str]:
    equipo = evidencia.equipo
    vibracion = evidencia.activa(equipo, "vibracion", "alta")
    temperatura = evidencia.activa(equipo, "temperatura_aceite", "alta")
    succion = evidencia.activa(equipo, "presion_succion", "baja")
    caudal = evidencia.activa(CAUDALIMETRO, "caudal", "baja")
    dp_alta = any(
        evidencia.activa(tag, "presion_diferencial", "alta") for tag in FILTROS
    )
    dp_baja = any(
        evidencia.activa(tag, "presion_diferencial", "baja") for tag in FILTROS
    )
    pulsacion = evidencia.firma_recorrida("aguja_manometro_oscila", equipo)
    actuales = {
        "vibracion_sube": vibracion,
        "vibracion_acelera": vibracion,
        "vibracion_moderada_sube": vibracion,
        "vibracion_sin_cambio": evidencia.ausente(equipo, "vibracion"),
        "temp_aceite_sube": temperatura,
        "temp_aceite_sube_gradual": temperatura,
        "succion_baja": succion,
        "succion_normal": evidencia.ausente(equipo, "presion_succion"),
        "succion_todas_bombas_baja": all(
            evidencia.activa(tag, "presion_succion", "baja") for tag in BOMBAS
        ),
        "caudal_baja": caudal,
        "caudal_baja_leve": caudal,
        "dp_filtro_sube": dp_alta,
        "dp_filtro_cae_de_golpe_bajo_alarma": dp_baja,
        "pulsacion_descarga_sube": pulsacion,
        "sin_pulsacion_descarga": not pulsacion,
        "valor_plano_sin_ruido": False,
        "deriva_sin_cambio_en_relacionadas": False,
    }
    for fila in FALLAS.values():
        for firma in fila["firma_recorrida"]:
            if firma in actuales:
                continue
            if firma == "manometro_diferencial_alto":
                actuales[firma] = any(
                    evidencia.firma_recorrida(firma, tag) for tag in FILTROS
                )
            else:
                actuales[firma] = evidencia.firma_recorrida(firma, equipo)
    return frozenset(firma for firma, presente in actuales.items() if presente)


def _ordenar(
    candidatos: list[tuple[str, dict, tuple[str, ...], tuple[str, ...]]],
    presentes: frozenset[str],
) -> list[tuple[str, dict, tuple[str, ...], tuple[str, ...]]]:
    vibracion = "vibracion_sube" in presentes
    pulsacion = "pulsacion_descarga_sube" in presentes
    temperatura = "temp_aceite_sube" in presentes
    succion = "succion_baja" in presentes
    caudal = "caudal_baja" in presentes
    succion_normal = "succion_normal" in presentes
    dp_alta = "dp_filtro_sube" in presentes
    dp_baja = "dp_filtro_cae_de_golpe_bajo_alarma" in presentes
    reglas = (
        (succion and vibracion, "F09"),
        (vibracion and pulsacion, "F02"),
        (vibracion and temperatura, "F03"),
        (vibracion and not pulsacion and not temperatura and not succion, "F06"),
        (temperatura and not vibracion, "F04"),
        (caudal and succion_normal, "F05"),
        (caudal, "F01"),
        (dp_alta, "F07"),
        (dp_baja, "F08"),
        ("lectura_local_no_coincide" in presentes, "F10"),
    )
    por_codigo = {candidato[0]: candidato for candidato in candidatos}
    ordenados = []
    usados = set()
    for aplica, codigo in reglas:
        if aplica and codigo in por_codigo and codigo not in usados:
            ordenados.append(por_codigo[codigo])
            usados.add(codigo)
    ordenados.extend(c for c in candidatos if c[0] not in usados)
    return ordenados


def verificar_cita(doc: str, seccion: str) -> bool:
    """Busca el id exacto ``doc §seccion`` en el índice y exige que esté vigente.

    ``tools._fragmentos_manuales()`` expone ``rag._obtener_retriever().por_id``,
    claveado por el id literal del fragmento; no usa ``rag.buscar`` ni su top 5.
    """
    try:
        por_id = tools._fragmentos_manuales()
    except Exception:
        return False
    fragmento = por_id.get(f"{doc} §{seccion}")
    if fragmento is None or fragmento.vigente is not True:
        return False
    return fragmento.doc in MANUALES_DOCS and fragmento.tipo in MANUALES_TIPOS


def _citas(codigo: str) -> tuple[str, ...]:
    documento, seccion = FALLAS[codigo]["cita"]
    if not verificar_cita(documento, seccion):
        return ()
    return (f"{documento} §{seccion}",)


def _accion_tarea_equipo(
    codigo: str,
    fila: dict,
    citas: tuple[str, ...],
    presentes: frozenset[str],
    evidencia: EvidenciaEquipo,
) -> tuple[str, str | None, str, str]:
    if codigo == "F10":
        return "sin_orden", fila["tarea"], fila["ejecutor"], evidencia.equipo
    if codigo == "F09":
        filtro = _primer_filtro(evidencia, "alta")
        if filtro is not None:
            return (
                "orden" if citas else "inspeccion",
                "T-F-CAR" if citas else None,
                "propio",
                filtro,
            )
        return "inspeccion", None, "propio", TANQUE
    if codigo in ("F07", "F08"):
        filtro = _primer_filtro(evidencia, "alta") or _primer_filtro(
            evidencia, "baja"
        )
        if filtro is None:
            filtro = next(
                (
                    anomalia.tag
                    for anomalia in evidencia.anomalias
                    if anomalia.tag in FILTROS
                    and anomalia.variable == "presion_diferencial"
                ),
                evidencia.equipo,
            )
            return "inspeccion", None, fila["ejecutor"], filtro
        return (
            "orden" if citas else "inspeccion",
            fila["tarea"] if citas else None,
            fila["ejecutor"],
            filtro,
        )
    sin_desempate = "vibracion_sube" in presentes and not any(
        firma in presentes
        for firma in (
            "pulsacion_descarga_sube",
            "temp_aceite_sube",
            "succion_baja",
            "caudal_baja",
        )
    )
    if not citas:
        if codigo == "F02":
            accion = "I-VAL"
        elif codigo in ("F03", "F06", "F09"):
            accion = "I-VIB"
        else:
            accion = "inspeccion"
    elif sin_desempate and codigo in ("F02", "F03", "F06"):
        accion = "I-VIB"
    else:
        accion = "orden"
    # Decisión de diseño: la inspección se propone como tarea no estándar cuando
    # la evidencia no desempata o no hay fragmento que respalde la conclusión;
    # no es una regla del manual.
    if accion in INSPECCIONES:
        return accion, accion, INSPECCIONES[accion], evidencia.equipo
    return accion, fila["tarea"], fila["ejecutor"], evidencia.equipo


def causas_probables(
    evidencia: EvidenciaEquipo,
    buscar: Callable[[str], Sequence[ManualEncontrado]] = manuales_buscar,
) -> list[Causa]:
    """Propone causas ordenadas; ``buscar`` queda por compatibilidad de firma.

    Las citas no dependen de ``buscar``: se verifican por id exacto en el índice.
    """
    presentes = _firmas_presentes(evidencia)
    candidatos = []
    for codigo, fila in FALLAS.items():
        firmas = (*fila["firma_sensores"], *fila["firma_recorrida"])
        encontradas = tuple(firma for firma in firmas if firma in presentes)
        if not any(firma not in NEGATIVAS for firma in encontradas):
            continue
        faltantes = tuple(firma for firma in firmas if firma not in presentes)
        candidatos.append((codigo, fila, encontradas, faltantes))
    causas = []
    for codigo, fila, encontradas, faltantes in _ordenar(candidatos, presentes):
        citas = _citas(codigo)
        accion, tarea, ejecutor, equipo_orden = _accion_tarea_equipo(
            codigo, fila, citas, presentes, evidencia
        )
        descripcion = f"{codigo} {fila['nombre']}"
        if codigo == "F08":
            descripcion += "; requiere inspección adicional (la fuente no especifica cuál)"
        if codigo == "F09" and equipo_orden == TANQUE:
            descripcion += "; causa raíz TK-301, requiere inspección"
        causas.append(
            Causa(
                codigo_falla=codigo,
                descripcion=descripcion,
                evidencia=encontradas,
                faltantes=faltantes,
                tarea_codigo=tarea,
                equipo_orden=equipo_orden,
                citas=citas,
                accion=accion,
                genera_orden=codigo != "F10",
                ejecutor=ejecutor,
            )
        )
    return causas
