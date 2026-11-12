import logging
import threading
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

MODELO = "base"
CPU_THREADS = 2
BEAM_SIZE = 5
PROMPT = (
    "La uno, la dos, la tres, la de la punta, la del medio, la del fondo, "
    "el filtro A, el filtro B, el pulmon, la bomba, descarga, diferencial, "
    "kilogramos, psi, grados, rodamiento, pistola, empaquetadura, goteo, "
    "aceite, correas."
)
CALENTAMIENTO = Path(__file__).with_name("calentamiento.wav")


class Transcriptor:
    def __init__(self) -> None:
        self._modelo: WhisperModel | None = None
        self._listo = threading.Event()

    def precargar(self) -> None:
        log.info("cargando whisper %s int8", MODELO)
        try:
            self._modelo = WhisperModel(
                MODELO,
                device="cpu",
                compute_type="int8",
                cpu_threads=CPU_THREADS,
                num_workers=1,
                local_files_only=True,
            )
            if CALENTAMIENTO.exists():
                audio = str(CALENTAMIENTO)
                vad = False
            else:
                audio = np.zeros(16000, dtype=np.float32)
                vad = True
            segmentos, _ = self._modelo.transcribe(
                audio,
                language="es",
                beam_size=BEAM_SIZE,
                vad_filter=vad,
                condition_on_previous_text=False,
                word_timestamps=False,
                initial_prompt=PROMPT,
            )
            for _ in segmentos:
                pass
            log.info("whisper listo")
        finally:
            # Si la carga falla, el worker no debe quedar esperando para siempre.
            self._listo.set()

    def transcribir(self, ruta: Path) -> str:
        self._listo.wait()
        if self._modelo is None:
            raise RuntimeError("Whisper no está cargado")
        segmentos, _ = self._modelo.transcribe(
            str(ruta),
            language="es",
            beam_size=BEAM_SIZE,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=False,
            initial_prompt=PROMPT,
        )
        return " ".join(s.text.strip() for s in segmentos).strip()
