import unittest
from datetime import datetime, timezone

from planta_contrato import (
    EstadoOrden,
    EventoSistema,
    NotaRecorrida,
    OrdenSistema,
    Repuesto,
    TipoEvento,
    Topicos,
)

from sistema.alertas import eventos_seguridad
from sistema.ordenes import (
    ContextoOrden,
    RegistroOrdenesMemoria,
    construir_orden,
    publicar_orden,
)
from sistema.reglas import MOTIVO_APROBADA
from sistema.repositorio_ordenes import ErrorPersistenciaOrden
from sistema.seguridad import Deteccion
from sistema.tools import stock, tareas_catalogo

TS = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
BOMBAS_CON_RESERVA = {"B-101": "marcha", "B-102": "parada", "B-103": "marcha"}
BOMBAS_TODAS_EN_MARCHA = {"B-101": "marcha", "B-102": "marcha", "B-103": "marcha"}


class PublicadorFalso:
    def __init__(self) -> None:
        self.publicados = []

    def __call__(self, topico, modelo) -> None:
        self.publicados.append((topico, modelo))


class PublicadorEventos(PublicadorFalso):
    def __init__(self, eventos) -> None:
        super().__init__()
        self.eventos = eventos

    def __call__(self, topico, modelo) -> None:
        self.eventos.append("publicar")
        super().__call__(topico, modelo)


class RepositorioOrdenesFalso:
    def __init__(self, eventos=None, error=None) -> None:
        self.eventos = [] if eventos is None else eventos
        self.guardadas = []
        self.error = error

    def guardar(self, orden) -> None:
        self.eventos.append("guardar")
        if self.error is not None:
            raise self.error
        self.guardadas.append(orden)

    def cargar_pendientes(self):
        return []


def evento_sensor(equipo="B-101", evento_id="EV-SENSOR-1"):
    return EventoSistema(
        id=evento_id,
        ts=TS,
        tipo=TipoEvento.escalado,
        equipo=equipo,
        origen="sensor",
        resumen="desvío de presión",
    )


def nota(fotos=None, nota_id="NOTA-1"):
    return NotaRecorrida(
        id=nota_id,
        ts=TS,
        operador="operador-1",
        audio_url=None,
        fotos=fotos or [],
        recorrida_id="REC-1",
    )


def evento_seguridad_s1(nota_):
    return eventos_seguridad(nota_, [Deteccion("S1", "agua a presión")])[0]


def contexto(
    equipo="B-101",
    evento=None,
    estado_bombas=None,
    notas=None,
    notas_analizadas=frozenset(),
    tareas=None,
    catalogo_stock=None,
):
    return ContextoOrden(
        tareas=tareas if tareas is not None else tareas_catalogo(),
        stock=catalogo_stock if catalogo_stock is not None else stock(equipo).items,
        estado_bombas=estado_bombas,
        eventos=(evento,) if evento is not None else (),
        notas=notas or {},
        notas_analizadas=notas_analizadas,
    )


class TestConstruirOrden(unittest.TestCase):
    def test_arma_borrador_con_id_determinista(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        otra = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        self.assertEqual(orden.estado, EstadoOrden.borrador)
        self.assertEqual(orden.id, otra.id)
        self.assertEqual(orden.evento_ids, [evento.id])
        self.assertEqual(orden.ts, evento.ts)
        self.assertFalse(orden.detiene_equipo)
        self.assertFalse(orden.reduce_inyeccion)

    def test_repuesto_fuera_de_lista_materiales_no_se_incluye(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="FC-CART-25", cantidad=1)],
        )
        self.assertEqual(orden.repuestos, [])

    def test_tarea_desconocida_detiene_y_reduce(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["NO-ESTANDAR"],
            ejecutor="propio",
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        self.assertTrue(orden.detiene_equipo)
        self.assertTrue(orden.reduce_inyeccion)

    def test_tarea_que_detiene_con_reserva_no_reduce(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_CON_RESERVA,
        )
        self.assertTrue(orden.detiene_equipo)
        self.assertFalse(orden.reduce_inyeccion)

    def test_tarea_que_detiene_sin_reserva_reduce(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        self.assertTrue(orden.reduce_inyeccion)

    def test_estado_de_bombas_desconocido_reduce(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=None,
        )
        self.assertTrue(orden.reduce_inyeccion)


class TestPublicarOrden(unittest.TestCase):
    def test_publica_orden_aprobada_de_bomba(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
            estado_bombas=BOMBAS_CON_RESERVA,
        )
        publicador = PublicadorFalso()
        decidida = publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=BOMBAS_CON_RESERVA),
            publicador,
            RegistroOrdenesMemoria(),
        )
        self.assertIsNotNone(decidida)
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)
        self.assertEqual(decidida.motivo, MOTIVO_APROBADA)
        self.assertEqual(len(publicador.publicados), 1)
        topico, publicado = publicador.publicados[0]
        self.assertEqual(topico, Topicos.ORDENES)
        self.assertEqual(publicado.id, orden.id)
        OrdenSistema.model_validate(publicado.model_dump(mode="json"))

    def test_publica_orden_aprobada_de_filtro(self):
        evento = evento_sensor(equipo="F-201A")
        orden = construir_orden(
            evento,
            "F-201A",
            ["T-F-CAR"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="FC-CART-25", cantidad=48)],
        )
        publicador = PublicadorFalso()
        decidida = publicar_orden(
            orden,
            contexto(equipo="F-201A", evento=evento),
            publicador,
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)
        self.assertFalse(decidida.detiene_equipo)

    def test_publica_orden_aprobada_de_instrumento(self):
        evento = evento_sensor(equipo="FT-401")
        orden = construir_orden(
            evento, "FT-401", ["T-I-CAL"], ejecutor="propio"
        )
        publicador = PublicadorFalso()
        decidida = publicar_orden(
            orden,
            contexto(equipo="FT-401", evento=evento),
            publicador,
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)
        self.assertFalse(decidida.detiene_equipo)

    def test_publica_pendiente_si_detiene_sin_reserva(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        decidida = publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA),
            PublicadorFalso(),
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.pendiente)
        self.assertEqual(decidida.motivo, "REDUCE_INYECCION")

    def test_publica_pendiente_si_estado_de_bombas_es_desconocido(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=None,
        )
        decidida = publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=None),
            PublicadorFalso(),
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.pendiente)
        self.assertEqual(decidida.motivo, "REDUCE_INYECCION")

    def test_tarea_no_estandar_con_contratista_queda_pendiente(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["NO-ESTANDAR"],
            ejecutor="Contratista del Sur",
            estado_bombas=BOMBAS_CON_RESERVA,
        )
        decidida = publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=BOMBAS_CON_RESERVA),
            PublicadorFalso(),
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.pendiente)
        self.assertIn("EJECUTOR_NO_PROPIO", decidida.motivo)

    def test_nunca_publica_un_borrador(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        publicador = PublicadorFalso()
        publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA),
            publicador,
            RegistroOrdenesMemoria(),
        )
        for _, publicado in publicador.publicados:
            self.assertNotEqual(publicado.estado, EstadoOrden.borrador)

    def test_no_republica_el_mismo_estado(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        ctx = contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA)
        publicador = PublicadorFalso()
        registro = RegistroOrdenesMemoria()
        primera = publicar_orden(orden, ctx, publicador, registro)
        segunda = publicar_orden(orden, ctx, publicador, registro)
        self.assertIsNotNone(primera)
        self.assertIsNone(segunda)
        self.assertEqual(len(publicador.publicados), 1)
        self.assertEqual(registro.get(primera.id), primera.estado)

    def test_cambio_de_estado_se_republica_con_el_mismo_id(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        ctx = contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA)
        publicador = PublicadorFalso()
        registro = RegistroOrdenesMemoria()
        primera = publicar_orden(orden, ctx, publicador, registro)
        aprobada = orden.model_copy(
            update={
                "estado": EstadoOrden.aprobada,
                "motivo": "aprobada por el planificador",
            }
        )
        segunda = publicar_orden(aprobada, ctx, publicador, registro)
        self.assertEqual(primera.estado, EstadoOrden.pendiente)
        self.assertEqual(segunda.estado, EstadoOrden.aprobada)
        self.assertEqual(len(publicador.publicados), 2)
        self.assertEqual(
            publicador.publicados[0][1].id, publicador.publicados[1][1].id
        )
        self.assertEqual(registro.get(orden.id), EstadoOrden.aprobada)
        tercera = publicar_orden(aprobada, ctx, publicador, registro)
        self.assertIsNone(tercera)
        self.assertEqual(len(publicador.publicados), 2)


class TestPublicarOrdenConRepositorio(unittest.TestCase):
    def _orden_y_contexto(self):
        evento = evento_sensor()
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-VAL"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="TX-VAL-KIT", cantidad=1)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        ctx = contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA)
        return orden, ctx

    def test_publicar_orden_sin_repo(self):
        orden, ctx = self._orden_y_contexto()
        publicador = PublicadorFalso()
        registro = RegistroOrdenesMemoria()

        decidida = publicar_orden(orden, ctx, publicador, registro)

        self.assertIsNotNone(decidida)
        self.assertEqual(len(publicador.publicados), 1)
        self.assertEqual(registro.get(decidida.id), decidida.estado)

    def test_publicar_orden_con_repo_guarda_antes_de_publicar(self):
        orden, ctx = self._orden_y_contexto()
        eventos = []
        repositorio = RepositorioOrdenesFalso(eventos)
        publicador = PublicadorEventos(eventos)

        decidida = publicar_orden(orden, ctx, publicador, None, repositorio)

        self.assertEqual(eventos, ["guardar", "publicar"])
        self.assertEqual(repositorio.guardadas, [decidida])
        self.assertNotEqual(decidida.estado, EstadoOrden.borrador)

    def test_publicar_orden_con_repo_que_falla(self):
        orden, ctx = self._orden_y_contexto()
        error = ErrorPersistenciaOrden("guardar orden", RuntimeError("api caida"))
        repositorio = RepositorioOrdenesFalso(error=error)
        publicador = PublicadorEventos([])

        with self.assertRaises(ErrorPersistenciaOrden):
            publicar_orden(orden, ctx, publicador, None, repositorio)

        self.assertEqual(publicador.publicados, [])
        self.assertEqual(repositorio.eventos, ["guardar"])


class TestFotos(unittest.TestCase):
    def _publicar(self, nota_, notas=None, notas_analizadas=frozenset()):
        evento = evento_seguridad_s1(nota_)
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        ctx = contexto(
            evento=evento,
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
            notas={nota_.id: nota_} if notas is None else notas,
            notas_analizadas=notas_analizadas,
        )
        return publicar_orden(
            orden, ctx, PublicadorFalso(), RegistroOrdenesMemoria()
        )

    def test_evento_seguridad_s1_con_fotos_queda_pendiente(self):
        nota_ = nota(fotos=["/media/fotos/fuga.jpg"])
        evento = evento_seguridad_s1(nota_)
        self.assertEqual(evento.nota_ids, [nota_.id])
        decidida = self._publicar(nota_)
        self.assertEqual(decidida.estado, EstadoOrden.pendiente)
        self.assertEqual(decidida.motivo, "FOTOS_PENDIENTES")

    def test_evento_seguridad_s1_sin_fotos_no_marca_fotos(self):
        decidida = self._publicar(nota(fotos=[]))
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)
        self.assertEqual(decidida.motivo, MOTIVO_APROBADA)

    def test_nota_con_fotos_ya_analizada_no_marca_fotos(self):
        nota_ = nota(fotos=["/media/fotos/fuga.jpg"])
        decidida = self._publicar(
            nota_, notas_analizadas=frozenset({nota_.id})
        )
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)

    def test_nota_vinculada_ausente_marca_fotos(self):
        nota_ = nota()
        decidida = self._publicar(nota_, notas={})
        self.assertEqual(decidida.estado, EstadoOrden.pendiente)
        self.assertEqual(decidida.motivo, "FOTOS_PENDIENTES")

    def test_evento_sin_nota_ids_no_marca_fotos(self):
        evento = evento_sensor()
        self.assertEqual(evento.nota_ids, [])
        orden = construir_orden(
            evento,
            "B-101",
            ["T-B-ACE"],
            ejecutor="propio",
            repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=8)],
            estado_bombas=BOMBAS_TODAS_EN_MARCHA,
        )
        decidida = publicar_orden(
            orden,
            contexto(evento=evento, estado_bombas=BOMBAS_TODAS_EN_MARCHA),
            PublicadorFalso(),
            RegistroOrdenesMemoria(),
        )
        self.assertEqual(decidida.estado, EstadoOrden.aprobada)


if __name__ == "__main__":
    unittest.main()
