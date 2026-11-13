import os
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agente"))

from agente.sistema import embeddings, indice_pg, indexado  # noqa: E402
from agente.sistema.config import EMBEDDING_DIM  # noqa: E402


class _CursorFalso:
    def __init__(self, filas=None):
        self.ejecutadas = []
        self._filas = filas or []
        self.cerrado = False

    def execute(self, sql, params=None):
        self.ejecutadas.append((sql, params))

    def fetchall(self):
        return self._filas

    def close(self):
        self.cerrado = True


class _ConexionFalsa:
    def __init__(self, filas=None):
        self.cur = _CursorFalso(filas)
        self.commits = 0
        self.cerrada = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        self.cerrada = True


class _CursorQueFalla(_CursorFalso):
    def execute(self, sql, params=None):
        raise RuntimeError("sin conexion")


class _ModeloFalso:
    def __init__(self, vector=None):
        self.vector = vector

    def embed(self, texto):
        if self.vector is not None:
            return list(self.vector)
        return [0.5] + [0.0] * (EMBEDDING_DIM - 1)


def _fragmento(id: str, texto: str, vigente: bool = True) -> indexado.Fragmento:
    return indexado.Fragmento(
        id=id,
        doc=id.split()[0],
        numero="1",
        titulo="Prueba",
        texto=texto,
        vigente=vigente,
        pagina=None,
        tipo="manual",
        archivo=None,
    )


class TestEmbeddingsHash(unittest.TestCase):
    def test_dim_fija(self):
        modelo = embeddings.obtener_modelo(["bomba triplex"])
        self.assertEqual(len(modelo.embed("bomba triplex")), EMBEDDING_DIM)

    def test_norma_l2_uno(self):
        modelo = embeddings.obtener_modelo(["bomba triplex"])
        vector = modelo.embed("bomba triplex")
        self.assertAlmostEqual(sum(x * x for x in vector) ** 0.5, 1.0, places=6)

    def test_cero_para_texto_vacio(self):
        modelo = embeddings.obtener_modelo(["algo"])
        self.assertEqual(modelo.embed(""), [0.0] * EMBEDDING_DIM)

    def test_determinista_entre_instancias(self):
        a = embeddings.obtener_modelo(["bomba triplex", "filtro de descarga"])
        b = embeddings.obtener_modelo(["bomba triplex", "filtro de descarga"])
        self.assertEqual(a.embed("bomba triplex"), b.embed("bomba triplex"))

    def test_bucket_usa_crc32(self):
        self.assertEqual(
            embeddings._bucket("bomba", EMBEDDING_DIM),
            zlib.crc32(b"bomba") % EMBEDDING_DIM,
        )


class TestIndicePgSQL(unittest.TestCase):
    def test_crear_tabla_habilita_vector(self):
        conexion = _ConexionFalsa()
        indice_pg.crear_tabla(conexion=conexion)
        sentencias = [sql for sql, _ in conexion.cur.ejecutadas]
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sentencias)
        self.assertTrue(any(f"vector({EMBEDDING_DIM})" in sql for sql in sentencias))
        self.assertEqual(conexion.commits, 0)
        self.assertTrue(conexion.cur.cerrado)

    def test_indexar_usa_on_conflict_y_vector(self):
        conexion = _ConexionFalsa()
        fragmentos = [
            _fragmento("TX350-D §3.2", "vibracion 7.1"),
            _fragmento("historial OT-25-0026", "se cambio la bomba"),
        ]
        total = indice_pg.indexar(fragmentos, _ModeloFalso(), conexion=conexion)
        self.assertEqual(total, 2)
        self.assertEqual(len(conexion.cur.ejecutadas), 2)
        for sql, params in conexion.cur.ejecutadas:
            self.assertIn("ON CONFLICT (id) DO UPDATE", sql)
            self.assertTrue(sql.strip().startswith("INSERT INTO fragmentos"))
            self.assertEqual(params[-1].count(","), EMBEDDING_DIM - 1)
        self.assertEqual(conexion.cur.ejecutadas[0][1][0], "TX350-D §3.2")

    def test_buscar_devuelve_score_e_id_y_filtra_vigentes(self):
        conexion = _ConexionFalsa([("TX350-D §3.2", 0.9), ("TX350-D §4.1", 0.4)])
        resultado = indice_pg.buscar(
            "vibracion", k=2, solo_vigentes=True, modelo=_ModeloFalso(), conexion=conexion
        )
        self.assertEqual(
            resultado, [(0.9, "TX350-D §3.2"), (0.4, "TX350-D §4.1")]
        )
        sql_busqueda, params = conexion.cur.ejecutadas[-1]
        self.assertIn("<=>", sql_busqueda)
        self.assertIn("vigente = true", sql_busqueda)
        self.assertIn("LIMIT", sql_busqueda)
        self.assertEqual(params[-1], 2)
        self.assertEqual(params[0], params[1])

    def test_buscar_sin_filtro_vigente(self):
        conexion = _ConexionFalsa([])
        indice_pg.buscar(
            "vibracion", k=3, solo_vigentes=False, modelo=_ModeloFalso(), conexion=conexion
        )
        sql_busqueda, _ = conexion.cur.ejecutadas[-1]
        self.assertNotIn("vigente = true", sql_busqueda)

    def test_buscar_error_devuelve_vacio(self):
        conexion = _ConexionFalsa()
        conexion.cur = _CursorQueFalla()
        resultado = indice_pg.buscar(
            "vibracion", modelo=_ModeloFalso(), conexion=conexion
        )
        self.assertEqual(resultado, [])

    def test_buscar_pregunta_vacia_no_consulta(self):
        conexion = _ConexionFalsa()
        modelo = _ModeloFalso([0.0] * EMBEDDING_DIM)
        resultado = indice_pg.buscar("", modelo=modelo, conexion=conexion)
        self.assertEqual(resultado, [])
        self.assertEqual(conexion.cur.ejecutadas, [])

    def test_buscar_sin_modelo_devuelve_vacio(self):
        self.assertEqual(indice_pg.buscar("vibracion"), [])


@unittest.skipUnless(os.getenv("POSTGRES_DSN"), "sin POSTGRES_DSN")
class TestIndicePgReal(unittest.TestCase):
    def test_indexar_y_buscar(self):
        fragmentos = [
            _fragmento("prueba-indice-pg §1", "vibracion alta en bomba triplex"),
            _fragmento("prueba-indice-pg §2", "presion de descarga baja"),
        ]
        modelo = embeddings.obtener_modelo([f.texto for f in fragmentos])
        indice_pg.crear_tabla()
        try:
            indice_pg.indexar(fragmentos, modelo)
            resultado = indice_pg.buscar(
                "vibracion bomba", k=1, solo_vigentes=True, modelo=modelo
            )
            self.assertEqual(resultado[0][1], "prueba-indice-pg §1")
        finally:
            with indice_pg._abrir_conexion() as conexion:
                with conexion.cursor() as cur:
                    cur.execute(
                        "DELETE FROM fragmentos WHERE id LIKE %s",
                        ("prueba-indice-pg %",),
                    )
                conexion.commit()
