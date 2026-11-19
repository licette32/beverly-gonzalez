import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sistema import indexado
from sistema.causas import (
    DP_ALARMA_ALTA,
    FALLAS,
    Anomalia,
    EvidenciaEquipo,
    causas_probables,
    lado_desde_limite,
    verificar_cita,
)
from sistema.parte import ItemParte


DESDE = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
HASTA = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
TS = datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc)
DOCS = (
    Path(__file__).resolve().parents[2]
    / "novit-curso"
    / "academia2026-tp"
    / "datos"
    / "documentos"
)
FRAGMENTOS = DOCS / "fragmentos.jsonl"
INDICE = DOCS / "indice.json"


def anomalia(tag, variable, lado):
    return Anomalia(tag, variable, TS, lado)


def evidencia(equipo, anomalias=(), partes=()):
    return EvidenciaEquipo(equipo, DESDE, HASTA, tuple(anomalias), tuple(partes))


class TestLadoDesdeLimite(unittest.TestCase):
    def test_lados_y_valores_sin_lado(self):
        self.assertEqual(lado_desde_limite("alarma_alta=7.1"), "alta")
        self.assertEqual(lado_desde_limite("alarma_baja=0.9"), "baja")
        self.assertIsNone(lado_desde_limite("fuera de rango"))
        self.assertIsNone(lado_desde_limite(None))
        self.assertIsNone(lado_desde_limite("alarma_alta=1, alarma_baja=0.1"))


class ConCitasVerificadas(unittest.TestCase):
    def setUp(self):
        parche = patch("sistema.causas.verificar_cita", return_value=True)
        self.verificar = parche.start()
        self.addCleanup(parche.stop)


class TestCausasProbables(ConCitasVerificadas):
    def test_f02_vibracion_y_pulsacion(self):
        ev = evidencia(
            "B-101",
            [
                anomalia("B-101", "vibracion", "alta"),
                anomalia("FT-401", "caudal", "baja"),
            ],
            [
                ItemParte(
                    "B-101",
                    "presion_descarga_local",
                    None,
                    None,
                    "pulsacion de descarga",
                )
            ],
        )
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F02")
        self.assertIn("vibracion_sube", causa.evidencia)
        self.assertIn("pulsacion_descarga_sube", causa.evidencia)
        self.assertIn("golpeteo_metalico", causa.faltantes)
        self.assertEqual(causa.tarea_codigo, "T-B-VAL")
        self.assertEqual(causa.equipo_orden, "B-101")
        self.assertEqual(causa.citas, ("MBP-4 §6.4",))
        self.assertEqual(causa.accion, "orden")
        self.assertEqual(causa.ejecutor, "propio")
        self.assertTrue(causa.genera_orden)

    def test_f04_temperatura_gradual_sin_vibracion(self):
        ev = evidencia(
            "B-102",
            [anomalia("B-102", "temperatura_aceite", "alta")],
            [ItemParte("B-102", "nivel_aceite_visor", None, None, "nivel de aceite bajo")],
        )
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F04")
        self.assertIn("temp_aceite_sube_gradual", causa.evidencia)
        self.assertIn("vibracion_sin_cambio", causa.evidencia)
        self.assertIn("visor_aceite_bajo", causa.evidencia)
        self.assertEqual(causa.tarea_codigo, "T-B-ACE")
        self.assertEqual(causa.citas, ("MBP-4 §6.6",))
        self.assertEqual(causa.accion, "orden")

    def test_f07_filtro_colmatado(self):
        ev = evidencia("F-201A", [anomalia("F-201A", "presion_diferencial", "alta")])
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F07")
        self.assertEqual(causa.equipo_orden, "F-201A")
        self.assertEqual(causa.tarea_codigo, "T-F-CAR")
        self.assertEqual(causa.citas, ("MBP-4 §6.9",))
        self.assertEqual(causa.accion, "orden")

    def test_f09_causa_raiz_en_filtro(self):
        ev = evidencia(
            "B-101",
            [
                anomalia("B-101", "presion_succion", "baja"),
                anomalia("B-101", "vibracion", "alta"),
                anomalia("F-201B", "presion_diferencial", "alta"),
            ],
        )
        causas = causas_probables(ev)
        self.assertEqual(causas[0].codigo_falla, "F09")
        self.assertEqual(causas[0].equipo_orden, "F-201B")
        self.assertEqual(causas[0].tarea_codigo, "T-F-CAR")
        self.assertNotEqual(causas[0].equipo_orden, "B-101")
        self.assertIn("F07", [causa.codigo_falla for causa in causas])

    def test_f09_sin_evidencia_de_filtro_va_al_tanque(self):
        ev = evidencia(
            "B-101",
            [
                anomalia("B-101", "presion_succion", "baja"),
                anomalia("B-101", "vibracion", "alta"),
            ],
        )
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F09")
        self.assertEqual(causa.equipo_orden, "TK-301")
        self.assertEqual(causa.accion, "inspeccion")
        self.assertIsNone(causa.tarea_codigo)
        self.assertIn("TK-301", causa.descripcion)
        self.assertTrue(causa.genera_orden)

    def test_f10_no_genera_orden(self):
        ev = evidencia(
            "FT-401",
            partes=[
                ItemParte(
                    "FT-401", "caudal", None, None, "lectura local no coincide"
                )
            ],
        )
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F10")
        self.assertEqual(causa.tarea_codigo, "T-I-CAL")
        self.assertEqual(causa.accion, "sin_orden")
        self.assertFalse(causa.genera_orden)

    def test_evidencia_insuficiente_da_inspeccion_vib(self):
        ev = evidencia("B-101", [anomalia("B-101", "vibracion", "alta")])
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F06")
        self.assertEqual(causa.accion, "I-VIB")
        self.assertEqual(causa.tarea_codigo, "I-VIB")
        self.assertEqual(causa.ejecutor, "contratista")
        self.assertEqual(causa.equipo_orden, "B-101")
        self.assertTrue(causa.genera_orden)

    def test_cita_inexistente_se_descarta(self):
        self.verificar.side_effect = lambda doc, seccion: seccion != "6.4"
        ev = evidencia(
            "B-101",
            [anomalia("B-101", "vibracion", "alta")],
            [
                ItemParte(
                    "B-101",
                    "presion_descarga_local",
                    None,
                    None,
                    "pulsacion de descarga",
                )
            ],
        )
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F02")
        self.assertEqual(causa.citas, ())
        self.assertEqual(causa.accion, "I-VAL")
        self.assertEqual(causa.tarea_codigo, "I-VAL")
        self.assertEqual(causa.ejecutor, "propio")

    def test_cita_no_vigente_se_descarta(self):
        self.verificar.side_effect = lambda doc, seccion: seccion != "6.9"
        ev = evidencia("F-201A", [anomalia("F-201A", "presion_diferencial", "alta")])
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.citas, ())
        self.assertIsNone(causa.tarea_codigo)
        self.assertEqual(causa.accion, "inspeccion")

    def test_f08_mantiene_t_f_car_sin_tarea_de_inspeccion(self):
        ev = evidencia("F-201A", [anomalia("F-201A", "presion_diferencial", "baja")])
        causa = causas_probables(ev)[0]
        self.assertEqual(causa.codigo_falla, "F08")
        self.assertEqual(causa.tarea_codigo, "T-F-CAR")
        self.assertIn("inspección", causa.descripcion)
        self.assertNotIn(causa.tarea_codigo, ("I-VIB", "I-VAL"))

    def test_lado_none_no_desempata_filtros(self):
        ev = evidencia(
            "B-101",
            [
                anomalia("B-101", "presion_succion", None),
                anomalia("B-101", "vibracion", None),
                anomalia("F-201A", "presion_diferencial", None),
            ],
        )
        causas = causas_probables(ev)
        self.assertEqual(causas[0].codigo_falla, "F09")
        self.assertEqual(causas[0].accion, "inspeccion")
        self.assertEqual(causas[0].equipo_orden, "TK-301")
        filtros = [c for c in causas if c.codigo_falla in ("F07", "F08")]
        self.assertTrue(filtros)
        self.assertTrue(
            all(c.accion == "inspeccion" and c.tarea_codigo is None for c in filtros)
        )

    def test_sin_evidencia_no_hay_candidatas(self):
        self.assertEqual(causas_probables(evidencia("B-101")), [])

    def test_firmas_negativas_no_crean_candidatas(self):
        ev = evidencia("F-201A", [anomalia("F-201A", "presion_diferencial", "alta")])
        codigos = [causa.codigo_falla for causa in causas_probables(ev)]
        self.assertEqual(codigos, ["F07"])
        self.assertNotIn("F04", codigos)
        self.assertNotIn("F05", codigos)
        self.assertNotIn("F06", codigos)

    def test_nivel_aceite_normal_no_dispara_f04(self):
        for observacion in ("normal", "ok", None):
            with self.subTest(observacion=observacion):
                ev = evidencia(
                    "B-102",
                    partes=[ItemParte("B-102", "nivel_aceite_visor", None, None, observacion)],
                )
                self.assertEqual(causas_probables(ev), [])

    def test_goteo_normal_y_rodamiento_templado_no_disparan(self):
        ev = evidencia(
            "B-101",
            partes=[
                ItemParte("B-101", "goteo_empaquetadura", None, "gotas/min", "normal"),
                ItemParte("B-101", "temperatura_rodamiento_ir", 50.0, "degC", None),
            ],
        )
        self.assertEqual(causas_probables(ev), [])

    def test_umbral_diferencial_sale_de_la_fuente(self):
        self.assertEqual(DP_ALARMA_ALTA, 1.5)
        baja = evidencia(
            "F-201A",
            partes=[ItemParte("F-201A", "presion_diferencial", 1.4, "kg/cm2", None)],
        )
        alta = evidencia(
            "F-201A",
            partes=[ItemParte("F-201A", "presion_diferencial", 1.6, "kg/cm2", None)],
        )
        self.assertEqual(causas_probables(baja), [])
        self.assertEqual(causas_probables(alta)[0].codigo_falla, "F07")


class TestIntegracionCitasReales(unittest.TestCase):
    def test_las_diez_citas_de_fallas_existen_y_estan_vigentes(self):
        if not FRAGMENTOS.exists() or not INDICE.exists():
            self.skipTest("índice documental del curso no disponible")
        fragmentos = indexado.cargar_desde_archivo(
            str(FRAGMENTOS), str(INDICE)
        )
        por_id = {fragmento.id: fragmento for fragmento in fragmentos}
        with patch("sistema.tools._fragmentos_manuales", return_value=por_id):
            for codigo, fila in FALLAS.items():
                documento, seccion = fila["cita"]
                with self.subTest(codigo=codigo):
                    self.assertTrue(verificar_cita(documento, seccion))
            ev = evidencia("F-201A", [anomalia("F-201A", "presion_diferencial", "alta")])
            self.assertEqual(
                causas_probables(ev)[0].citas, ("MBP-4 §6.9",)
            )


if __name__ == "__main__":
    unittest.main()
