import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

from planta_contrato import EstadoOrden, OrdenSistema, Repuesto

from sistema.config import POSTGRES_DSN
from sistema.repositorio_ordenes import (
    ESPERA_CONEXION_BASE_S,
    REINTENTOS_CONEXION,
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


@unittest.skipUnless(POSTGRES_DSN, "POSTGRES_DSN no configurado")
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

    def test_repositorio_ordenes_recrea_tabla_si_no_existe(self):
        primero = _id("antes-drop")
        segundo = _id("despues-drop")
        self.ids.extend([primero, segundo])
        self.repositorio.guardar(_orden(primero, EstadoOrden.aprobada))

        _ejecutar(self.repositorio, "DROP TABLE ordenes")
        self.repositorio.guardar(_orden(segundo, EstadoOrden.aprobada))

        self.assertEqual(_contar(self.repositorio, segundo), 1)

    def test_guardar_si_estado_actualiza_solo_si_coincide(self):
        orden_id = _id("condicional")
        self.ids.append(orden_id)
        self.repositorio.guardar(_orden(orden_id, EstadoOrden.pendiente))
        aprobada = _orden(orden_id, EstadoOrden.aprobada)

        self.assertTrue(
            self.repositorio.guardar_si_estado(
                aprobada, EstadoOrden.pendiente
            )
        )
        self.assertEqual(self.repositorio.obtener(orden_id).estado, EstadoOrden.aprobada)
        self.assertFalse(
            self.repositorio.guardar_si_estado(
                _orden(orden_id, EstadoOrden.cerrada), EstadoOrden.pendiente
            )
        )
        self.assertEqual(self.repositorio.obtener(orden_id).estado, EstadoOrden.aprobada)

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

    def test_ordenes_abiertas_filtra_estados_y_equipo(self):
        abiertos = (
            EstadoOrden.pendiente,
            EstadoOrden.aprobada,
            EstadoOrden.ejecutada,
            EstadoOrden.observada,
        )
        cerrados = (
            EstadoOrden.rechazada,
            EstadoOrden.cerrada,
            EstadoOrden.certificada,
        )
        ids = {
            estado: _id(f"abierta-{estado.value}") for estado in (*abiertos, *cerrados)
        }
        otro_equipo = _orden(_id("otro-equipo"), EstadoOrden.aprobada).model_copy(
            update={"equipo": "B-102"}
        )
        self.ids.extend([*ids.values(), otro_equipo.id])
        for estado, orden_id in ids.items():
            self.repositorio.guardar(_orden(orden_id, estado))
        self.repositorio.guardar(otro_equipo)

        devueltas = [
            orden
            for orden in self.repositorio.ordenes_abiertas("B-101")
            if orden.id in ids.values()
        ]

        self.assertEqual(
            {orden.id for orden in devueltas},
            {ids[estado] for estado in abiertos},
        )

class TestConexionPereza(unittest.TestCase):
    def test_init_no_crea_tablas_ni_conecta(self):
        with (
            patch.object(RepositorioOrdenesPostgres, "_crear_tablas") as crear,
            patch.object(RepositorioOrdenesPostgres, "_abrir_conexion") as abrir,
        ):
            repositorio = RepositorioOrdenesPostgres("dsn-falso")

        crear.assert_not_called()
        abrir.assert_not_called()
        self.assertEqual(repositorio._dsn, "dsn-falso")
        self.assertIsNone(repositorio._conexion)

    def test_abrir_conexion_reintenta_con_backoff(self):
        conexion = MagicMock()
        modulo = MagicMock()
        modulo.connect.side_effect = [
            ConnectionError("todavía no"),
            ConnectionError("otra vez"),
            conexion,
        ]
        with (
            patch("sistema.repositorio_ordenes._psycopg", return_value=modulo),
            patch("sistema.repositorio_ordenes.time.sleep") as dormir,
        ):
            repositorio = RepositorioOrdenesPostgres("dsn-falso")
            self.assertIs(repositorio._abrir_conexion(), conexion)

        self.assertEqual(modulo.connect.call_count, 3)
        self.assertEqual(
            dormir.call_args_list,
            [
                call(ESPERA_CONEXION_BASE_S),
                call(ESPERA_CONEXION_BASE_S * 2),
            ],
        )

    def test_abrir_conexion_agota_reintentos_y_levanta(self):
        modulo = MagicMock()
        modulo.connect.side_effect = ConnectionError("postgres caído")
        with (
            patch("sistema.repositorio_ordenes._psycopg", return_value=modulo),
            patch("sistema.repositorio_ordenes.time.sleep") as dormir,
        ):
            repositorio = RepositorioOrdenesPostgres("dsn-falso")
            with self.assertRaises(ConnectionError):
                repositorio._abrir_conexion()

        self.assertEqual(modulo.connect.call_count, REINTENTOS_CONEXION)
        self.assertEqual(dormir.call_count, REINTENTOS_CONEXION - 1)

    def test_tabla_inexistente_se_recrea_una_vez(self):
        repositorio = RepositorioOrdenesPostgres("dsn-falso")
        conexion = MagicMock()
        cursor = conexion.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = [
            RuntimeError('relation "ordenes" does not exist'),
            None,
        ]
        with (
            patch.object(
                repositorio, "_abrir_conexion", return_value=conexion
            ),
            patch.object(repositorio, "_crear_tablas") as crear,
        ):
            repositorio.guardar(_orden("tabla-inexistente", EstadoOrden.aprobada))

        crear.assert_called_once_with()
        self.assertEqual(cursor.execute.call_count, 2)

    def test_guardar_con_postgres_caido_levanta_error(self):
        repositorio = RepositorioOrdenesPostgres("dsn-falso")
        with patch.object(
            repositorio, "_abrir_conexion", side_effect=RuntimeError("api caida")
        ) as abrir:
            with self.assertRaises(ErrorPersistenciaOrden) as contexto:
                repositorio.guardar(_orden("caido", EstadoOrden.aprobada))

        self.assertEqual(contexto.exception.operacion, "guardar orden")
        self.assertIsInstance(contexto.exception.__cause__, RuntimeError)
        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
