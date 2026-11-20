from __future__ import annotations

import argparse
import json
import logging
import sys

from sistema.config import MQTT_HOST, MQTT_PORT, POSTGRES_DSN, SISTEMA
from sistema.mqtt import ClienteMQTT
from sistema.ordenes import ErrorEstadoEsperado, publicar_orden
from sistema.repositorio_cierres import RepositorioCierresPostgres
from sistema.repositorio_ordenes import (
    ErrorPersistenciaOrden,
    RepositorioOrdenesPostgres,
)
from sistema.transiciones import Accion, ErrorTransicion, transicionar

log = logging.getLogger(__name__)

ACCIONES = {
    "aprobar": Accion.aprobar,
    "rechazar": Accion.rechazar,
    "cerrar": Accion.cerrar,
    "certificar": Accion.certificar,
    "observar": Accion.observar,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sistema.cli")
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--por", help="nombre del operador")
    subcomandos = parser.add_subparsers(dest="comando", required=True)

    subcomandos.add_parser("aprobar", parents=[comun]).add_argument("orden_id")
    rechazar = subcomandos.add_parser("rechazar", parents=[comun])
    rechazar.add_argument("orden_id")
    rechazar.add_argument("--motivo", required=True)
    subcomandos.add_parser("cerrar", parents=[comun]).add_argument("orden_id")
    certificar = subcomandos.add_parser("certificar", parents=[comun])
    certificar.add_argument("orden_id")
    certificar.add_argument("--habilita", required=True)
    certificar.add_argument("--monto", required=True, type=float)
    observar = subcomandos.add_parser("observar", parents=[comun])
    observar.add_argument("orden_id")
    observar.add_argument("--motivo", required=True)
    subcomandos.add_parser("cierre").add_argument("orden_id")
    return parser


def main(argv=None, repositorio=None, cliente=None, repositorio_cierres=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.comando != "cierre" and not args.por:
        parser.error("--por es obligatorio")
    log.info(
        "cli comando=%s orden=%s por=%s",
        args.comando,
        args.orden_id,
        getattr(args, "por", None),
    )

    if args.comando == "cierre":
        if repositorio_cierres is None:
            if not POSTGRES_DSN:
                print("POSTGRES_DSN no configurado", file=sys.stderr)
                return 1
            repositorio_cierres = RepositorioCierresPostgres(POSTGRES_DSN)
        filas = repositorio_cierres.listar_por_orden(args.orden_id)
        if not filas:
            print(f"sin cierres para la orden {args.orden_id}", file=sys.stderr)
            return 1
        for fila in filas:
            print(
                json.dumps(
                    {
                        "nota_id": fila.nota.id,
                        "estado": fila.estado,
                        "parte": fila.parte,
                        "diferencias": fila.diferencias,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0

    if repositorio is None:
        if not POSTGRES_DSN:
            print("POSTGRES_DSN no configurado", file=sys.stderr)
            return 1
        repositorio = RepositorioOrdenesPostgres(POSTGRES_DSN)

    propio = cliente is None
    if propio:
        cliente = ClienteMQTT(MQTT_HOST, MQTT_PORT, f"{SISTEMA}-cli")
        try:
            cliente.conectar()
        except (OSError, RuntimeError) as exc:
            print(f"no se pudo conectar a MQTT: {exc}", file=sys.stderr)
            return 1

    try:
        leida = repositorio.obtener(args.orden_id)
        if leida is None:
            print(f"orden {args.orden_id} no encontrada", file=sys.stderr)
            return 1

        try:
            nueva = transicionar(
                leida,
                ACCIONES[args.comando],
                motivo=getattr(args, "motivo", None),
                habilita=getattr(args, "habilita", None),
                monto_habilita_usd=getattr(args, "monto", None),
            )
            publicada = publicar_orden(
                nueva,
                None,
                cliente.publicar,
                repositorio=repositorio,
                estado_esperado=leida.estado,
            )
        except ErrorTransicion as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (ErrorEstadoEsperado, ErrorPersistenciaOrden) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        estado = publicada.estado if publicada is not None else nueva.estado
        log.info("cli aplicada orden=%s estado=%s", args.orden_id, estado.value)
        print(f"{args.orden_id}: {estado.value}")
        return 0
    finally:
        if propio:
            cliente.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
