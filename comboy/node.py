"""Runtime del nodo: loop de recepción, manejo de tramas, logging y TTS.

Alcance de Fase 0 (nivel de banco de pruebas L0): recibir una trama,
decodificarla, registrarla y pronunciarla. Flooding, deduplicación, backoff,
CAD, roster, heartbeats y expiración de alertas quedan deliberadamente fuera
de alcance y viven en :meth:`Node._handle_frame` como el punto de extensión
para la Fase 3.
"""

from __future__ import annotations

from . import __version__
from .codes import ROLE_NAMES, MsgType, Role, as_confidence, as_hazard, as_lane, as_urgency
from .config import Config
from .frame import AlertFrame, decode
from .logging_setup import Logger
from .phrase import build_phrase
from .transport import Transport
from .tts import Speaker


class Node:
    """Un único nodo de comboy: es dueño de un transporte, un logger y un speaker."""

    def __init__(
        self,
        config: Config,
        transport: Transport,
        logger: Logger,
        speaker: Speaker | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger
        self._speaker = speaker if speaker is not None else Speaker(logger=logger)

    def run(self) -> None:
        """Corre el loop de recepción bloqueante hasta que se interrumpa o se cierre."""

        self._logger.info("boot", version=__version__, config="loaded")
        try:
            for data, origin in self._transport.recv_frames():
                self._handle_frame(data, origin)
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
            self._logger.info("shutdown")

    def send_alert(self, frame: AlertFrame) -> None:
        """Codifica y transmite una trama de alerta, registrando ``alert.tx``."""

        data = frame.encode()
        self._transport.send_frame(data)
        self._logger.info(
            "alert.tx",
            alert_id=f"{frame.alert_id:08x}",
            hop=frame.hop,
            ttl=frame.ttl,
            hazard=as_hazard(frame.hazard).name,
            lane=as_lane(frame.lane).name,
            dist_km=frame.dist_km,
            urgency=as_urgency(frame.urgency).name,
            confidence=as_confidence(frame.confidence).name,
        )

    def _handle_frame(self, data: bytes, origin: str) -> None:
        """Maneja un datagrama recibido.

        Este es el punto de extensión de la Fase 3: el flooding, la caché de
        dedup, el roster y la FSM de alertas se enchufan aquí. La Fase 0 solo
        decodifica, registra y pronuncia.
        """

        frame = decode(data)
        if frame is None:
            self._logger.warn("frame.invalid", origin=origin, length=len(data))
            return

        if frame.msg_type != MsgType.ALERTA:
            # El manejo de Heartbeat/JOIN/LEAVE es trabajo de la Fase 3.
            return

        self._logger.info(
            "alert.rx",
            alert_id=f"{frame.alert_id:08x}",
            from_node=frame.origin_id,
            role=ROLE_NAMES.get(_coerce_role(frame.origin_role), "follower"),
            origin=origin,
            hop=frame.hop,
            ttl=frame.ttl,
            hazard=as_hazard(frame.hazard).name,
            lane=as_lane(frame.lane).name,
            dist_km=frame.dist_km,
            urgency=as_urgency(frame.urgency).name,
            confidence=as_confidence(frame.confidence).name,
        )

        phrase = build_phrase(frame)
        self._speaker.speak(phrase)
        self._logger.info("tts.play", text=phrase)

    def close(self) -> None:
        """Cierra el transporte limpiamente."""

        close = getattr(self._transport, "close", None)
        if callable(close):
            close()


def _coerce_role(value: int) -> Role:
    try:
        return Role(value)
    except ValueError:
        return Role.SEGUIDOR


__all__ = ["Node"]
