import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from planta_contrato import EstadoOrden, OrdenSistema, Repuesto

from sistema.config import POSTGRES_DSN
from sistema.repositorio_ordenes import (
    ErrorPersistenciaOrden,
    RepositorioOrdenesPostgres,
)

SUFIJO = uuid.uuid4().hex[:10]


def _id(nombre: str) -> str:
    return f"test-repo-ordenes-{SUFIJO}-{nombre}"


def _orden(orden_id: str, estado: EstadoOrden, motivo=None) -> OrdenSistema:
    return OrdenSistema(
        id=orden_id,
        ts=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
        estado=estado,
        equipo="B-101",
        evento_ids=[f"evt-{orden_id}"],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor="propio",
        repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=1)],
        motivo=motivo,
    )


def _ejecutar(repositorio, sql, params=None, fetch=None):
    conexion = repositorio._abrir_conexion()
    try:
        with conexion.cursor() as cursor:
            cursor.execute(sql, params)
            resultado = fetch(cursor) if fetch is not None else None
        conexion.commit()
        return resultado
    finally:
        conexion.close()


def _contar(repositorio, orden_id: str) -> int:
    fila = _ejecutar(
        repositorio,
        "SELECT count(*) FROM ordenes WHERE id = %s",
        (orden_id,),
        lambda cursor: cursor.fetchone(),
    )
    return int(fila[0])


def _limpiar(repositorio, ids) -> None:
    for orden_id in ids:
        _ejecutar(repositorio, "DELETE FROM ordenes WHERE id = %s", (orden_id,))


class TestRepositorioOrdenesPostgres(unittest.TestCase):
    def setUp(self) -> None:
        self.repositorio = RepositorioOrdenesPostgres(POSTGRES_DSN)
        self.ids: list[str] = []

    def tearDown(self) -> None:
        try:
            _limpiar(self.repositorio, self.ids)
        finally:
            self.repositorio.cerrar()

    def test_guardar_dos_veces_no_duplica(self):
        orden_id = _id("upsert")
        self.ids.append(orden_id)

        self.repositorio.guardar(_orden(orden_id, EstadoOrden.aprobada))
        self.repositorio.guardar(
            _orden(orden_id, EstadoOrden.rechazada, motivo="no cumple")
        )

        self.assertEqual(_contar(self.repositorio, orden_id), 1)
        self.assertEqual(
            self.repositorio.obtener(orden_id).estado, EstadoOrden.rechazada
        )

    def test_obtener_tras_nueva_instancia(self):
        orden = _orden(_id("nueva-instancia"), EstadoOrden.aprobada)
        self.ids.append(orden.id)
        self.repositorio.guardar(orden)

        otro = RepositorioOrdenesPostgres(POSTGRES_DSN)
        try:
            cargada = otro.obtener(orden.id)
        finally:
            otro.cerrar()

        self.assertIsNotNone(cargada)
        self.assertEqual(cargada.model_dump(mode="json"), orden.model_dump(mode="json"))

    def test_cargar_pendientes_filtra_estados(self):
        ids = {
            EstadoOrden.borrador: _id("borrador"),
            EstadoOrden.pendiente: _id("pendiente"),
            EstadoOrden.aprobada: _id("aprobada"),
            EstadoOrden.rechazada: _id("rechazada"),
        }
        self.ids.extend(ids.values())
        for estado, orden_id in ids.items():
            self.repositorio.guardar(_orden(orden_id, estado))

        devueltos = [
            orden
            for orden in self.repositorio.cargar_pendientes()
            if orden.id in ids.values()
        ]

        self.assertEqual(
            {orden.id for orden in devueltos},
            {ids[EstadoOrden.borrador], ids[EstadoOrden.pendiente]},
        )
        self.assertEqual(
            {orden.estado for orden in devueltos},
            {EstadoOrden.borrador, EstadoOrden.pendiente},
        )

    def test_guardar_con_postgres_caido_levanta_error(self):
        orden_id = _id("caido")
        self.ids.append(orden_id)
        orden = _orden(orden_id, EstadoOrden.aprobada)

        with patch.object(
            self.repositorio, "_abrir_conexion", side_effect=RuntimeError("api caida")
        ) as abrir:
            with self.assertRaises(ErrorPersistenciaOrden) as contexto:
                self.repositorio.guardar(orden)

        self.assertEqual(contexto.exception.operacion, "guardar orden")
        self.assertIsInstance(contexto.exception.__cause__, RuntimeError)
        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
