import logging
import os
import subprocess
import sys
import time

from planta_contrato import Topicos

from .anomalias import ParametrosDeteccion
from .anomalias_recientes import AlmacenAnomalias
from .catalogo import CatalogoPlanta
from .cierres import ManejadorCierres, WorkerCierres
from .config import (
    ENLACE_SONDA_INTERVALO_S,
    ENLACE_SONDA_TIMEOUT_S,
    ENLACE_SONDA_URL,
    HEARTBEAT_S,
    INDEXAR_PG_AL_ARRANCAR,
    LOG_LEVEL,
    MQTT_HOST,
    MQTT_PORT,
    PLANTA_BASE_URL,
    POSTGRES_DSN,
    SENSORES_ANOMALIA_MINIMO,
    SENSORES_ANOMALIA_SPAN_MIN,
    SENSORES_ANOMALIA_VENTANA_MIN,
    SENSORES_HORIZONTE_HORAS,
    SENSORES_MAX_LECTURAS,
    SISTEMA,
)
from .coordinador import CoordinadorPartes
from .eventos_sensores import WorkerSensores
from .heartbeat import ColaPendientes, Latido, SondaEnlace
from .mqtt import ClienteMQTT
from .ordenes_worker import WorkerOrdenes
from .repositorio import crear_repositorio
from .repositorio_cierres import RepositorioCierresPostgres
from .repositorio_decisiones import RepositorioDecisionesPostgres
from .repositorio_ordenes import RepositorioOrdenesPostgres
from .sensores import VentanaSensores
from .transcripcion import Transcriptor
from .worker import WorkerNotas

TOPICOS = [
    Topicos.RECORRIDAS,
    Topicos.CIERRES,
    Topicos.ENERGIA,
    Topicos.RESPUESTAS,
    "planta/sensores/+/+",
]


def _lanzar_indexado() -> None:
    """Lanza el indexado como proceso separado; si falla, loguea y sigue."""
    try:
        cmd = [sys.executable, "-m", "sistema.indexar"]
        log = logging.getLogger(__name__)
        log.info("Lanzando indexado pgvector: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=log.handlers[0].stream if log.handlers else sys.stdout,
            stderr=sys.stderr,
            preexec_fn=lambda: os.nice(19),
        )
        log.info("Indexado lanzado en PID %d (continuarÃ© sin esperar)", proc.pid)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "No se pudo lanzar el indexado: %s", exc
        )


def main() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    transcriptor = Transcriptor()
    cliente = ClienteMQTT(MQTT_HOST, MQTT_PORT, SISTEMA)
    repositorio = crear_repositorio(POSTGRES_DSN)
    repositorio_ordenes = (
        RepositorioOrdenesPostgres(POSTGRES_DSN) if POSTGRES_DSN else None
    )
    repositorio_cierres = (
        RepositorioCierresPostgres(POSTGRES_DSN) if POSTGRES_DSN else None
    )
    registro_decisiones = (
        RepositorioDecisionesPostgres(POSTGRES_DSN) if POSTGRES_DSN else None
    )
    almacen_anomalias = AlmacenAnomalias()
    cola_pendientes = ColaPendientes()
    sonda_enlace = SondaEnlace(
        url=ENLACE_SONDA_URL,
        timeout_s=ENLACE_SONDA_TIMEOUT_S,
        intervalo_s=ENLACE_SONDA_INTERVALO_S,
        al_cambio=cola_pendientes.actualizar_enlace,
    )

    def pendientes_totales() -> int:
        return repositorio.pendientes_sincronizar() + cola_pendientes.cantidad()

    worker_ordenes = (
        WorkerOrdenes(
            cliente.publicar, repositorio_ordenes, registro=registro_decisiones
        )
        if repositorio_ordenes is not None
        else None
    )
    worker_cierres = (
        WorkerCierres(
            repositorio_cierres,
            repositorio_ordenes,
            transcriptor,
            publicador=cliente.publicar,
            registro=registro_decisiones,
        )
        if repositorio_cierres is not None and repositorio_ordenes is not None
        else None
    )
    encolar_orden = worker_ordenes.encolar if worker_ordenes is not None else None
    if worker_ordenes is None:
        logging.getLogger(__name__).warning(
            "sin repositorio de órdenes: no se generan órdenes automáticas"
        )
    cierres_worker_no_arranco = False
    if worker_cierres is None:
        logging.getLogger(__name__).warning(
            "sin repositorio de cierres: los cierres no se procesan"
        )
    catalogo = CatalogoPlanta()
    coordinador = CoordinadorPartes(
        cliente,
        repositorio,
        catalogo,
        repositorio_ordenes=repositorio_ordenes,
        almacen_anomalias=almacen_anomalias,
        encolar_orden=encolar_orden,
        pendientes=cola_pendientes,
        registro=registro_decisiones,
    )
    worker = WorkerNotas(cliente, transcriptor, coordinador)
    ventana_sensores = VentanaSensores(
        SENSORES_HORIZONTE_HORAS, SENSORES_MAX_LECTURAS
    )
    worker_sensores = WorkerSensores(
        cliente,
        ventana_sensores,
        catalogo.limites,
        ParametrosDeteccion(
            SENSORES_ANOMALIA_VENTANA_MIN,
            SENSORES_ANOMALIA_MINIMO,
            SENSORES_ANOMALIA_SPAN_MIN,
        ),
        almacen_anomalias=almacen_anomalias,
        encolar_orden=encolar_orden,
        pendientes=cola_pendientes,
    )
    cliente.al_recibir_nota = worker.encolar
    cliente.al_recibir_respuesta = coordinador.encolar_respuesta
    cliente.al_recibir_sensor = worker_sensores.encolar

    # Primero se reciben y descargan las notas y el latido queda vivo; la
    # transcripción espera a que el modelo esté listo. Así no se pierde una nota
    # si la carga tarda. Postgres se conecta después, en segundo plano.
    cliente.conectar()
    if worker_cierres is not None:
        try:
            worker_cierres.start()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "No se pudo iniciar el worker de cierres: %s", exc
            )
            cliente.al_recibir_cierre = None
            worker_cierres.detener()
            worker_cierres = None
            cierres_worker_no_arranco = True
        else:
            cliente.al_recibir_cierre = ManejadorCierres(
                repositorio_ordenes,
                cliente.publicar,
            repositorio_cierres,
            worker_cierres.encolar,
            registro=registro_decisiones,
        )

    if cierres_worker_no_arranco:
        logging.getLogger(__name__).warning(
            "los cierres no se procesan porque el worker no arrancó"
        )
    if worker_ordenes is not None:
        worker_ordenes.start()
    if repositorio_ordenes is None:
        logging.getLogger(__name__).warning(
            "sin repositorio de órdenes tras los reintentos: no se reanudan pendientes"
        )
    else:
        coordinador.reanudar_pendientes()
    worker.start()
    worker_sensores.start()
    coordinador.iniciar()
    cliente.suscribir(TOPICOS)

    sonda_enlace.start()
    latido = Latido(
        cliente,
        SISTEMA,
        HEARTBEAT_S,
        pendientes=pendientes_totales,
        enlace_ok=lambda: sonda_enlace.arriba,
    )
    latido.start()

    try:
        repositorio.iniciar()
        _lanzar_indexado()
        catalogo.refrescar()
        transcriptor.precargar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sonda_enlace.detener()
        sonda_enlace.join(timeout=2)
        latido.detener()
        latido.join(timeout=2)
        worker_sensores.detener()
        worker_sensores.join(timeout=2)
        coordinador.detener()
        repositorio.detener()
        worker.detener()
        worker.join(timeout=35)
        if worker_ordenes is not None:
            worker_ordenes.detener()
            worker_ordenes.join(timeout=2)
        if worker_cierres is not None:
            worker_cierres.detener()
            worker_cierres.join(timeout=2)
        cliente.cerrar()


if __name__ == "__main__":
    main()
