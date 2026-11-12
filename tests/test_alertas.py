import unittest
from datetime import datetime, timezone

from planta_contrato import EventoSistema, MensajeTablet, NotaRecorrida

from sistema.alertas import eventos_seguridad, mensaje_seguridad
from sistema.seguridad import Deteccion


class TestAlertas(unittest.TestCase):
    def setUp(self):
        self.nota = NotaRecorrida(
            id="NOTA-00001",
            ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
            operador="operador-1",
            audio_url="/media/audios/NOTA-00001.wav",
            fotos=[],
            recorrida_id="REC-1",
        )
        self.detecciones = [
            Deteccion("S1", "agua a presion"),
            Deteccion("S2", "olor a gas"),
        ]

    def test_eventos_validan_contra_contrato(self):
        eventos = eventos_seguridad(self.nota, self.detecciones)
        self.assertEqual(len(eventos), 2)
        for evento in eventos:
            self.assertIsInstance(evento, EventoSistema)
            EventoSistema.model_validate(evento.model_dump(mode="json"))
            self.assertEqual(evento.tipo.value, "AlertaSeguridad")
            self.assertEqual(evento.origen, "parte")
            self.assertEqual(evento.nota_ids, [self.nota.id])
            self.assertEqual(evento.ts, self.nota.ts)

    def test_mensaje_valida_contra_contrato(self):
        mensaje = mensaje_seguridad(self.nota, self.detecciones)
        self.assertIsInstance(mensaje, MensajeTablet)
        MensajeTablet.model_validate(mensaje.model_dump(mode="json"))
        self.assertEqual(mensaje.nota_ids, [self.nota.id])
        self.assertEqual(mensaje.ts, self.nota.ts)
        self.assertFalse(mensaje.espera_respuesta)
        self.assertIn("supervisor", mensaje.texto)
        fila = mensaje.pantalla.filas[0]
        self.assertEqual(fila.variable, "condicion_insegura")
        self.assertIsNone(fila.valor)

    def test_ids_son_estables_para_la_misma_nota(self):
        eventos_1 = eventos_seguridad(self.nota, self.detecciones)
        eventos_2 = eventos_seguridad(self.nota, self.detecciones)
        self.assertEqual([e.id for e in eventos_1], [e.id for e in eventos_2])
        self.assertEqual(
            mensaje_seguridad(self.nota, self.detecciones).id,
            mensaje_seguridad(self.nota, self.detecciones).id,
        )


if __name__ == "__main__":
    unittest.main()
