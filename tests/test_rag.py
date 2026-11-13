import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agente"))

from agente.sistema import embeddings, indexado, rag  # noqa: E402


class TestEmbeddingsTFIDF(unittest.TestCase):
    def test_mismo_texto_misma_vector(self):
        e = embeddings.EmbeddingsTFIDF(["la uno esta en ciento quince"])
        self.assertEqual(e.embed("la uno esta en ciento quince"), e.embed("la uno esta en ciento quince"))

    def test_texto_diferente_vector_diferente(self):
        e = embeddings.EmbeddingsTFIDF(["la dos", "la uno"])
        self.assertNotEqual(e.embed("la dos"), e.embed("la uno"))

    def test_vector_normalizado_l2(self):
        e = embeddings.EmbeddingsTFIDF(["ciento quince"])
        v = e.embed("ciento quince")
        self.assertAlmostEqual(sum(x*x for x in v) ** 0.5, 1.0, places=6)

    def test_vector_zero_para_vacio(self):
        e = embeddings.EmbeddingsTFIDF(["algo"])
        self.assertEqual(e.embed(""), [0.0] * len(e._vocabulario))


class TestIndexado(unittest.TestCase):
    def test_cargar_desde_archivo(self):
        fragmentos = [
            {"id": "TX350-D §3.2", "doc": "TX350-D", "numero": "3.2", "titulo": "Limites", "texto": "vibracion 7.1", "vigente": True, "pagina": 20, "tipo": "manual"},
            {"id": "TX350-C §3.2", "doc": "TX350-C", "numero": "3.2", "titulo": "Limites viejos", "texto": "vibracion 4.5", "vigente": False, "pagina": 20, "tipo": "manual"},
            {"id": "historial OT-25-0026", "doc": "historial", "numero": "OT-25-0026", "titulo": "Orden", "texto": "cambio de valido", "vigente": True, "pagina": None, "tipo": "historial"},
        ]
        tmp = Path(__file__).parent / "test_frags.jsonl"
        tmp.write_text("\n".join(json.dumps(f) for f in fragmentos) + "\n", encoding="utf-8")
        try:
            fs = indexado.cargar_desde_archivo(str(tmp))
            self.assertEqual(len(fs), 3)
            self.assertTrue(fs[0].vigente)
            self.assertFalse(fs[1].vigente)
            self.assertTrue(fs[2].vigente)
            self.assertEqual(fs[0].id, "TX350-D §3.2")
            self.assertEqual(fs[1].id, "TX350-C §3.2")
        finally:
            tmp.unlink(missing_ok=True)

    def test_tipo_automatizado(self):
        tmp = Path(__file__).parent / "test_frags2.jsonl"
        tmp.write_text(
            json.dumps({
                "id": "TX350-D §1", "doc": "TX350-D", "numero": "1", "titulo": "Gen",
                "texto": "x", "vigente": True, "pagina": 1, "tipo": "manual"
            })
            + "\n",
            encoding="utf-8"
        )
        try:
            fs = indexado.cargar_desde_archivo(str(tmp))
            self.assertEqual(fs[0].tipo, "manual")
        finally:
            tmp.unlink(missing_ok=True)

    def test_para_pgvector_no_inicia_embedding(self):
        fragmentos = [
            {"id": "TX350-D §3.2", "doc": "TX350-D", "numero": "3.2", "titulo": "Limites", "texto": "vibracion 7.1", "vigente": True, "pagina": 20, "tipo": "manual"},
            {"id": "TX350-C §3.2", "doc": "TX350-C", "numero": "3.2", "titulo": "Limites viejos", "texto": "vibracion 4.5", "vigente": False, "pagina": 20, "tipo": "manual"},
            {"id": "historial OT-25-0026", "doc": "historial", "numero": "OT-25-0026", "titulo": "Orden", "texto": "cambio de valido", "vigente": True, "pagina": None, "tipo": "historial"},
        ]
        tmp = Path(__file__).parent / "test_frags_pg.jsonl"
        tmp.write_text("\n".join(json.dumps(f) for f in fragmentos) + "\n", encoding="utf-8")
        try:
            fs = indexado.cargar_desde_archivo(str(tmp))
            rows = indexado.para_pgvector(fs)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all("embedding" in r and r["embedding"] is None for r in rows))
        finally:
            tmp.unlink(missing_ok=True)
