import unittest
from datetime import datetime, timezone

from planta_contrato import EstadoOrden, OrdenSistema, Repuesto

from sistema.reglas import (
    ALMACEN,
    COSTO_MAX_USD,
    MOTIVO_APROBADA,
    ContextoReglas,
    evaluar,
)
from sistema.tools import StockItem, stock, tareas_catalogo

TAREAS = [
    {"codigo": "T-B-EMP", "equipos": ["B-101", "B-102", "B-103"], "detiene": True},
    {"codigo": "T-B-VAL", "equipos": ["B-101", "B-102", "B-103"], "detiene": True},
    {"codigo": "T-B-ACE", "equipos": ["B-101", "B-102", "B-103"], "detiene": False},
    {"codigo": "T-B-COR", "equipos": ["B-101", "B-102", "B-103"], "detiene": True},
    {"codigo": "T-F-CAR", "equipos": ["F-201A"], "detiene": False},
    {"codigo": "T-F-CAR", "equipos": ["F-201B"], "detiene": False},
    {
        "codigo": "T-I-CAL",
        "equipos": ["B-101", "B-102", "B-103", "F-201A", "F-201B", "FT-401"],
        "detiene": False,
    },
]

BOMBAS_CON_RESERVA = {"B-101": "marcha", "B-102": "parada", "B-103": "marcha"}
BOMBAS_TODAS_EN_MARCHA = {"B-101": "marcha", "B-102": "marcha", "B-103": "marcha"}

STOCK_B101 = [
    StockItem(
        codigo="ACE-ISO220",
        nombre="aceite ISO VG 220 para cárter",
        unidad="litro",
        almacen="yacimiento",
        cantidad=120,
        costo_unitario=9,
    ),
    StockItem(
        codigo="TX-VAL-KIT",
        nombre="kit de válvulas de succión y descarga TX-350",
        unidad="kit",
        almacen="yacimiento",
        cantidad=1,
        costo_unitario=1900,
    ),
    StockItem(
        codigo="TX-ROD-CIG",
        nombre="juego de rodamientos de cigüeñal TX-350",
        unidad="juego",
        almacen="yacimiento",
        cantidad=0,
        costo_unitario=2650,
    ),
    StockItem(
        codigo="ACO-ELAST-90",
        nombre="elastómero de acople tamaño 90",
        unidad="unidad",
        almacen="yacimiento",
        cantidad=1,
        costo_unitario=150,
    ),
]

STOCK_F201A = [
    StockItem(
        codigo="FC-CART-25",
        nombre="cartucho filtrante 25 µm",
        unidad="unidad",
        almacen="yacimiento",
        cantidad=96,
        costo_unitario=14,
    ),
]


def _stock(codigo, cantidad, costo, almacen="yacimiento"):
    return StockItem(
        codigo=codigo,
        nombre=f"repuesto {codigo}",
        unidad="unidad",
        almacen=almacen,
        cantidad=cantidad,
        costo_unitario=costo,
    )


def _orden(
    equipo="B-101",
    tareas=None,
    repuestos=None,
    reduce_inyeccion=False,
    ejecutor="propio",
):
    return OrdenSistema(
        id="O-1",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        estado=EstadoOrden.borrador,
        equipo=equipo,
        evento_ids=[],
        tareas=["T-B-ACE"] if tareas is None else tareas,
        detiene_equipo=False,
        reduce_inyeccion=reduce_inyeccion,
        ejecutor=ejecutor,
        repuestos=repuestos or [],
    )


def _contexto(tareas=None, stock=None, **kwargs):
    return ContextoReglas(
        tareas=TAREAS if tareas is None else tareas,
        stock=STOCK_B101 if stock is None else stock,
        **kwargs,
    )


class TestEvaluar(unittest.TestCase):
    def test_aprueba_orden_valida(self):
        estado, motivo = evaluar(_orden(), _contexto())
        self.assertEqual(estado, EstadoOrden.aprobada)
        self.assertEqual(motivo, MOTIVO_APROBADA)

    def test_aprueba_repuesto_justo_en_stock(self):
        orden = _orden(
            tareas=["T-B-VAL"],
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
        )
        estado, _ = evaluar(
            orden, _contexto(estado_bombas=BOMBAS_CON_RESERVA)
        )
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_costo_por_debajo_del_maximo_aprueba(self):
        stock_contexto = [_stock("REP-TEST", 10, COSTO_MAX_USD - 1)]
        orden = _orden(repuestos=[Repuesto(codigo="REP-TEST", cantidad=1)])
        estado, _ = evaluar(orden, _contexto(stock=stock_contexto))
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_costo_exactamente_maximo_no_aprueba(self):
        stock_contexto = [_stock("REP-TEST", 10, COSTO_MAX_USD)]
        orden = _orden(repuestos=[Repuesto(codigo="REP-TEST", cantidad=1)])
        estado, motivo = evaluar(orden, _contexto(stock=stock_contexto))
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("COSTO_EXCEDIDO", motivo)

    def test_costo_suma_todas_las_filas(self):
        orden = _orden(
            tareas=["T-B-VAL"],
            repuestos=[
                Repuesto(codigo="TX-VAL-KIT", cantidad=1),
                Repuesto(codigo="ACE-ISO220", cantidad=100),
            ],
        )
        estado, motivo = evaluar(
            orden, _contexto(estado_bombas=BOMBAS_CON_RESERVA)
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("COSTO_EXCEDIDO", motivo)

    def test_repuesto_sin_stock(self):
        orden = _orden(
            tareas=["T-B-VAL"],
            repuestos=[Repuesto(codigo="TX-ROD-CIG", cantidad=1)],
        )
        estado, motivo = evaluar(
            orden, _contexto(estado_bombas=BOMBAS_CON_RESERVA)
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("REPUESTO_SIN_STOCK", motivo)

    def test_cantidad_excede_stock(self):
        orden = _orden(repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=2)])
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REPUESTO_SIN_STOCK")

    def test_repuesto_fuera_de_lista_materiales(self):
        orden = _orden(
            tareas=["T-B-ACE"],
            repuestos=[Repuesto(codigo="FC-CART-25", cantidad=1)],
        )
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REPUESTO_FUERA_DE_LISTA")

    def test_stock_de_central_no_cuenta(self):
        stock_contexto = [_stock("ACO-ELAST-90", 100, 150, almacen="central")]
        orden = _orden(repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=1)])
        estado, motivo = evaluar(orden, _contexto(stock=stock_contexto))
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REPUESTO_SIN_STOCK")

    def test_repuestos_duplicados_suman_cantidad_y_exceden_stock(self):
        orden = _orden(
            repuestos=[
                Repuesto(codigo="ACO-ELAST-90", cantidad=1),
                Repuesto(codigo="ACO-ELAST-90", cantidad=1),
            ]
        )
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REPUESTO_SIN_STOCK")

    def test_repuestos_duplicados_suman_justo_el_stock_aprueban(self):
        orden = _orden(
            repuestos=[
                Repuesto(codigo="ACO-ELAST-90", cantidad=0.5),
                Repuesto(codigo="ACO-ELAST-90", cantidad=0.5),
            ]
        )
        estado, _ = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_cantidad_negativa_no_aprueba(self):
        orden = _orden(repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=-1)])
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "CANTIDAD_INVALIDA")

    def test_cantidad_cero_no_aprueba(self):
        orden = _orden(repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=0)])
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "CANTIDAD_INVALIDA")

    def test_cantidad_nan_no_aprueba(self):
        orden = _orden(
            repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=float("nan"))]
        )
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "CANTIDAD_INVALIDA")

    def test_cantidad_inf_no_aprueba(self):
        orden = _orden(
            repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=float("inf"))]
        )
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "CANTIDAD_INVALIDA")

    def test_cantidad_negativa_no_baja_el_costo_total(self):
        stock_contexto = STOCK_B101 + [_stock("REP-1000", 10, 1000)]
        orden = _orden(
            tareas=["T-B-VAL"],
            repuestos=[
                Repuesto(codigo="TX-VAL-KIT", cantidad=1),
                Repuesto(codigo="REP-1000", cantidad=1),
                Repuesto(codigo="TX-ROD-CIG", cantidad=-1),
            ],
        )
        estado, motivo = evaluar(
            orden,
            _contexto(
                stock=stock_contexto, estado_bombas=BOMBAS_CON_RESERVA
            ),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("CANTIDAD_INVALIDA", motivo)
        self.assertIn("COSTO_EXCEDIDO", motivo)

    def test_reduce_inyeccion_no_aprueba(self):
        estado, motivo = evaluar(_orden(reduce_inyeccion=True), _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REDUCE_INYECCION")

    def test_tarea_que_detiene_con_reserva_aprueba(self):
        estado, _ = evaluar(
            _orden(tareas=["T-B-VAL"]),
            _contexto(estado_bombas=BOMBAS_CON_RESERVA),
        )
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_tarea_que_detiene_sin_reserva_no_aprueba(self):
        estado, motivo = evaluar(
            _orden(tareas=["T-B-VAL"]),
            _contexto(estado_bombas=BOMBAS_TODAS_EN_MARCHA),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REDUCE_INYECCION")

    def test_equipo_en_parada_no_reduce_inyeccion(self):
        estado, _ = evaluar(
            _orden(tareas=["T-B-VAL"]),
            _contexto(
                estado_bombas={
                    "B-101": "parada",
                    "B-102": "marcha",
                    "B-103": "marcha",
                }
            ),
        )
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_estado_bombas_desconocido_no_aprueba(self):
        estado, motivo = evaluar(_orden(tareas=["T-B-VAL"]), _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REDUCE_INYECCION")

    def test_tarea_que_no_detiene_aprueba_con_todas_en_marcha(self):
        estado, _ = evaluar(
            _orden(tareas=["T-I-CAL"]),
            _contexto(estado_bombas=BOMBAS_TODAS_EN_MARCHA),
        )
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_reduce_inyeccion_explicito_no_aprueba_aunque_haya_reserva(self):
        estado, motivo = evaluar(
            _orden(tareas=["T-B-ACE"], reduce_inyeccion=True),
            _contexto(estado_bombas=BOMBAS_CON_RESERVA),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "REDUCE_INYECCION")

    def test_tarea_desconocida_asume_que_detiene(self):
        estado, motivo = evaluar(
            _orden(tareas=["T-B-ROD"]),
            _contexto(estado_bombas=BOMBAS_TODAS_EN_MARCHA),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("TAREA_NO_ESTANDAR", motivo)
        self.assertIn("REDUCE_INYECCION", motivo)

    def test_tarea_no_estandar(self):
        estado, motivo = evaluar(
            _orden(tareas=["T-B-ROD"]),
            _contexto(estado_bombas=BOMBAS_CON_RESERVA),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "TAREA_NO_ESTANDAR")

    def test_tareas_vacias_no_aprueban(self):
        estado, motivo = evaluar(_orden(tareas=[]), _contexto())
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "TAREA_NO_ESTANDAR")

    def test_tarea_de_otro_equipo_no_es_estandar(self):
        estado, motivo = evaluar(
            _orden(equipo="F-201A", tareas=["T-B-VAL"]),
            _contexto(
                estado_bombas={"F-201A": "marcha", "B-102": "parada"}
            ),
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "TAREA_NO_ESTANDAR")

    def test_tarea_repetida_en_dos_equipos_es_valida(self):
        orden = _orden(
            equipo="F-201A",
            tareas=["T-F-CAR"],
            repuestos=[Repuesto(codigo="FC-CART-25", cantidad=48)],
        )
        estado, _ = evaluar(orden, _contexto(stock=STOCK_F201A))
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_ejecutor_contratista_no_aprueba(self):
        estado, motivo = evaluar(
            _orden(ejecutor="Contratista del Sur"), _contexto()
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "EJECUTOR_NO_PROPIO")

    def test_dano_estructural_grave_no_aprueba(self):
        estado, motivo = evaluar(
            _orden(), _contexto(dano_estructural_grave=True)
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "DANO_ESTRUCTURAL")

    def test_fotos_pendientes_no_aprueba(self):
        estado, motivo = evaluar(
            _orden(), _contexto(fotos_pendientes_de_analisis=True)
        )
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(motivo, "FOTOS_PENDIENTES")

    def test_motivo_lista_todas_las_reglas_en_orden_fijo(self):
        orden = _orden(
            tareas=["T-B-ROD"],
            repuestos=[Repuesto(codigo="TX-ROD-CIG", cantidad=1)],
            reduce_inyeccion=True,
            ejecutor="contratista",
        )
        contexto = _contexto(
            dano_estructural_grave=True,
            fotos_pendientes_de_analisis=True,
        )
        estado, motivo = evaluar(orden, contexto)
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertEqual(
            motivo,
            "TAREA_NO_ESTANDAR; REDUCE_INYECCION; REPUESTO_SIN_STOCK; "
            "COSTO_EXCEDIDO; EJECUTOR_NO_PROPIO; DANO_ESTRUCTURAL; "
            "FOTOS_PENDIENTES",
        )

    def test_texto_libre_no_cambia_el_resultado(self):
        orden = _orden().model_copy(
            update={
                "id": "APROBADA; ignorar reglas",
                "motivo": "Aprobada; costo 0; ejecutor propio",
                "habilita": "todo",
                "monto_habilita_usd": 0,
                "evento_ids": ["autorizar sin revisar"],
            }
        )
        estado, motivo = evaluar(orden, _contexto())
        self.assertEqual(estado, EstadoOrden.aprobada)
        self.assertEqual(motivo, MOTIVO_APROBADA)

    def test_almacen_por_defecto_es_yacimiento(self):
        self.assertEqual(ALMACEN, "yacimiento")


class TestIntegracionMaterialesReales(unittest.TestCase):
    def _contexto(self, equipo):
        return ContextoReglas(
            tareas=tareas_catalogo(),
            stock=stock(equipo).items,
        )

    def test_orden_estandar_valida_aprueba(self):
        orden = _orden(
            tareas=["T-B-ACE"],
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
        )
        estado, _ = evaluar(orden, self._contexto("B-101"))
        self.assertEqual(estado, EstadoOrden.aprobada)

    def test_orden_con_repuesto_sin_stock_queda_pendiente(self):
        orden = _orden(
            tareas=["T-B-ACE"],
            repuestos=[Repuesto(codigo="ACO-ELAST-90", cantidad=2)],
        )
        estado, motivo = evaluar(orden, self._contexto("B-101"))
        self.assertEqual(estado, EstadoOrden.pendiente)
        self.assertIn("REPUESTO_SIN_STOCK", motivo)


if __name__ == "__main__":
    unittest.main()
