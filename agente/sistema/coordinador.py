from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime, timezone

from planta_contrato import NotaRecorrida, RespuestaOperador, Topicos

from .alertas import eventos_seguridad, mensaje_seguridad
from .ambiguedades import (
    Ambiguedad,
    detectar,
    items_para_b1,
    items_para_pantalla,
)
from .borradores import borrador, items_seguridad, pregunta
from .catalogo import CatalogoPlanta, historian_rango
from .config import PREGUNTA_TIMEOUT_S
from .corte import MAX_CORRECCIONES, mensaje_corte
from .eventos import eventos_parte
from .interpretacion import interpretar
from .mqtt import ClienteMQTT
from .parte import ItemParte, extraer_items
from .repositorio import EstadoNota, RepositorioMemoria
from .seguridad import Deteccion

log = logging.getLogger(__name__)


class CoordinadorPartes:
    def __init__(
        self,
        cliente: ClienteMQTT,
        repositorio: RepositorioMemoria,
        catalogo: CatalogoPlanta,
        timeout_pregunta_s: float = PREGUNTA_TIMEOUT_S,
    ) -> None:
        self._cliente = cliente
        self._repositorio = repositorio
        self._catalogo = catalogo
        self._timeout_pregunta_s = timeout_pregunta_s
        self._cola: queue.Queue[RespuestaOperador | None] = queue.Queue()
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    def iniciar(self) -> None:
        if self._hilo is not None:
            return
        self._hilo = threading.Thread(
            target=self._bucle_respuestas, name="respuestas", daemon=True
        )
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        self._cola.put_nowait(None)
        if self._hilo is not None:
            self._hilo.join(timeout=3)

    def encolar_respuesta(self, respuesta: RespuestaOperador) -> None:
        self._cola.put_nowait(respuesta)

    def procesar_nota(
        self, nota: NotaRecorrida, texto: str, detecciones: list[Deteccion]
    ) -> None:
        if detecciones:
            self._procesar_seguridad(nota, texto, detecciones)
            return
        self._procesar_parte(nota, texto)

    def _procesar_seguridad(
        self, nota: NotaRecorrida, texto: str, detecciones: list[Deteccion]
    ) -> None:
        for evento in eventos_seguridad(nota, detecciones):
            self._cliente.publicar(Topicos.EVENTOS, evento)
        self._cliente.publicar(Topicos.TABLET, mensaje_seguridad(nota, detecciones))

        items = items_seguridad(detecciones)
        mensaje = borrador(
            nota,
            items,
            0,
            texto=(
                "Alerta de seguridad. Además te dejo el parte de lo que escuché "
                "para que lo revises."
            ),
        )
        estado = EstadoNota(
            nota_id=nota.id,
            mensaje=mensaje,
            nota=nota,
            borrador=mensaje.pantalla.filas if mensaje.pantalla else [],
            items=items,
            texto=texto,
            intento=0,
            estado="BORRADOR",
        )
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        log.info("nota %s seguridad: alerta, aviso y borrador publicados", nota.id)

    def _procesar_parte(self, nota: NotaRecorrida, texto: str) -> None:
        items = extraer_items(texto, self._catalogo.unidades_manometro())
        ambiguedades = detectar(items, texto, self._catalogo)
        if ambiguedades:
            self._publicar_pregunta(nota, texto, items, ambiguedades, 0, 1)
            return

        for evento in eventos_parte(nota, items):
            self._cliente.publicar(Topicos.EVENTOS, evento)
        mensaje = borrador(nota, items, 0)
        estado = EstadoNota(
            nota_id=nota.id,
            mensaje=mensaje,
            nota=nota,
            borrador=mensaje.pantalla.filas if mensaje.pantalla else [],
            items=items,
            texto=texto,
            intento=0,
            estado="BORRADOR",
        )
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        log.info(
            "nota %s borrador publicado items=%s", nota.id, len(items)
        )

    def _publicar_pregunta(
        self,
        nota: NotaRecorrida,
        texto: str,
        items: list[ItemParte],
        ambiguedades: list[Ambiguedad],
        intento: int,
        secuencia: int,
    ) -> None:
        partes = [ambiguedad.pregunta for ambiguedad in ambiguedades]
        for ambiguedad in ambiguedades:
            if ambiguedad.tipo != "valor":
                continue
            item = items[ambiguedad.indice]
            if item.tag is None:
                continue
            rango = historian_rango(item.tag, item.variable, nota.ts)
            if rango is not None:
                minimo, maximo = rango
                partes.append(
                    f"Dato adicional del histórico de 12 h para {item.tag}: "
                    f"entre {minimo:g} y {maximo:g}. Igual confirmame qué leíste."
                )
        opciones = []
        for ambiguedad in ambiguedades:
            for opcion in ambiguedad.opciones:
                if opcion not in opciones:
                    opciones.append(opcion)
        texto_mensaje = " ".join(partes)
        visibles = items_para_pantalla(items, ambiguedades)
        mensaje = pregunta(
            nota,
            visibles,
            intento,
            secuencia,
            texto_mensaje,
            opciones,
        )
        estado = EstadoNota(
            nota_id=nota.id,
            mensaje=mensaje,
            nota=nota,
            borrador=mensaje.pantalla.filas if mensaje.pantalla else [],
            items=items,
            texto=texto,
            intento=intento,
            estado="PREGUNTA",
            pregunta=mensaje,
        )
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        self._programar_timeout(nota.id, mensaje.id)
        log.info(
            "nota %s pregunta publicada ambigüedades=%s",
            nota.id,
            [ambiguedad.tipo for ambiguedad in ambiguedades],
        )

    def _publicar_borrador_resuelto(self, estado: EstadoNota) -> None:
        for evento in eventos_parte(estado.nota, estado.items):
            self._cliente.publicar(Topicos.EVENTOS, evento)
        mensaje = borrador(estado.nota, estado.items, estado.intento)
        estado.mensaje = mensaje
        estado.borrador = mensaje.pantalla.filas if mensaje.pantalla else []
        estado.pregunta = None
        estado.estado = "BORRADOR"
        estado.actualizado_ts = datetime.now(timezone.utc)
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        log.info("nota %s borrador resuelto y B1 publicados", estado.nota_id)

    def _programar_timeout(self, nota_id: str, mensaje_id: str) -> None:
        timer = threading.Timer(
            self._timeout_pregunta_s,
            self._timeout_pregunta,
            args=(nota_id, mensaje_id),
        )
        timer.daemon = True
        with self._lock:
            self._timers[mensaje_id] = timer
        timer.start()

    def _cancelar_timeout(self, mensaje_id: str) -> None:
        with self._lock:
            timer = self._timers.pop(mensaje_id, None)
        if timer is not None:
            timer.cancel()

    def _timeout_pregunta(self, nota_id: str, mensaje_id: str) -> None:
        estado = self._repositorio.obtener_nota(nota_id)
        if (
            estado is None
            or estado.estado != "PREGUNTA"
            or estado.pregunta is None
            or estado.pregunta.id != mensaje_id
        ):
            return
        ambiguedades = detectar(estado.items, estado.texto, self._catalogo)
        for evento in eventos_parte(estado.nota, items_para_b1(estado.items, ambiguedades)):
            self._cliente.publicar(Topicos.EVENTOS, evento)
        visibles = items_para_pantalla(estado.items, ambiguedades, timeout=True)
        mensaje = borrador(
            estado.nota,
            visibles,
            estado.intento,
            texto=(
                "No llegó tu respuesta. Te dejo el borrador con lo que quedó "
                "sin confirmar marcado en la observación."
            ),
        )
        estado.mensaje = mensaje
        estado.borrador = mensaje.pantalla.filas if mensaje.pantalla else []
        estado.pregunta = None
        estado.estado = "BORRADOR"
        estado.actualizado_ts = datetime.now(timezone.utc)
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        log.warning(
            "nota %s sin respuesta a la pregunta %s; borrador y B1 publicados",
            nota_id,
            mensaje_id,
        )

    def _bucle_respuestas(self) -> None:
        while True:
            respuesta = self._cola.get()
            try:
                if respuesta is None:
                    return
                self._procesar_respuesta(respuesta)
            except Exception:
                log.exception("falló el procesamiento de una respuesta")
            finally:
                self._cola.task_done()

    def _procesar_respuesta(self, respuesta: RespuestaOperador) -> None:
        estado = self._repositorio.obtener_por_mensaje(respuesta.mensaje_id)
        if estado is None:
            log.warning("respuesta a mensaje desconocido %s", respuesta.mensaje_id)
            return
        self._repositorio.guardar_respuesta(respuesta)
        log.info(
            "nota %s respuesta a %s: %s",
            estado.nota_id,
            respuesta.mensaje_id,
            respuesta.texto,
        )

        resultado = interpretar(respuesta.texto, estado, self._catalogo)
        if resultado.tipo == "sin_entender":
            log.warning(
                "nota %s respuesta no entendida: %s", estado.nota_id, respuesta.texto
            )
            return

        if estado.estado == "PREGUNTA":
            if resultado.tipo != "correccion":
                return
            self._cancelar_timeout(respuesta.mensaje_id)
            estado.items = resultado.items
            ambiguedades = detectar(estado.items, estado.texto, self._catalogo)
            if ambiguedades:
                secuencia = 1
                if estado.pregunta is not None:
                    secuencia += 1
                self._publicar_pregunta(
                    estado.nota,
                    estado.texto,
                    estado.items,
                    ambiguedades,
                    estado.intento,
                    secuencia,
                )
                return
            self._publicar_borrador_resuelto(estado)
            return

        if resultado.tipo == "confirmacion":
            estado.estado = "CONFIRMADO"
            estado.actualizado_ts = datetime.now(timezone.utc)
            self._repositorio.guardar_estado(estado)
            log.info("nota %s confirmada", estado.nota_id)
            return

        if estado.intento >= MAX_CORRECCIONES:
            log.warning(
                "nota %s alcanzó el máximo de %s correcciones; se avisa y se detiene",
                estado.nota_id,
                MAX_CORRECCIONES,
            )
            self._cliente.publicar(
                Topicos.TABLET, mensaje_corte(estado.nota, "correcciones")
            )
            return
        estado.items = resultado.items
        estado.intento += 1
        mensaje = borrador(estado.nota, estado.items, estado.intento)
        estado.mensaje = mensaje
        estado.borrador = mensaje.pantalla.filas if mensaje.pantalla else []
        estado.estado = "BORRADOR"
        estado.actualizado_ts = datetime.now(timezone.utc)
        self._repositorio.guardar_estado(estado)
        self._cliente.publicar(Topicos.TABLET, mensaje)
        log.info(
            "nota %s corregida; borrador intento %s publicado",
            estado.nota_id,
            estado.intento,
        )
