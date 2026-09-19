"""Transporte UDP para el banco de pruebas (docs/09-banco-de-pruebas.md).

La trama de 17 bytes viaja sin cambios como payload del datagrama UDP: sin
wrapper, sin JSON, sin serialización extra. Eso mantiene el camino de datos
idéntico byte a byte al futuro enlace LoRa.
"""

from __future__ import annotations

import contextlib
import queue
import socket
import threading
from collections.abc import Iterator

from ..logging_setup import Logger

#: Datagrama más grande que estamos dispuestos a leer. Las tramas son de 17
#: bytes; el límite es generoso para que un datagrama sobredimensionado o
#: corrupto se lea y luego lo rechace el codec, en vez de truncarse en silencio.
_RECV_BUFFER = 2048

#: Timeout del socket que usa el hilo lector para poder notar ``close()``.
_READ_TIMEOUT_S = 0.5


def parse_address(value: str) -> tuple[str, int]:
    """Parsea ``"host:port"`` a ``(host, port)``."""

    host, separator, port_text = value.rpartition(":")
    if not separator or not port_text:
        raise ValueError(f"dirección inválida {value!r}, se esperaba 'host:port'")
    return host, int(port_text)


class UdpTransport:
    """Envía a una lista de pares configurada; recibe vía ``recvfrom`` en su propio hilo."""

    def __init__(self, bind: str, peers: list[str], logger: Logger | None = None) -> None:
        self._logger = logger
        self._peers = [parse_address(peer) for peer in peers]
        self._closed = threading.Event()
        self._queue: queue.Queue[tuple[bytes, str] | None] = queue.Queue()
        self._reader: threading.Thread | None = None

        bind_host, bind_port = parse_address(bind)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, bind_port))
        self._sock.settimeout(_READ_TIMEOUT_S)

    @property
    def local_address(self) -> tuple[str, int]:
        """El ``(host, port)`` realmente bindeado (útil con el puerto 0)."""

        return self._sock.getsockname()

    def send_frame(self, frame: bytes) -> None:
        """Envía ``frame`` a cada par. Nunca propaga errores de red."""

        for host, port in self._peers:
            try:
                self._sock.sendto(frame, (host, port))
            except OSError as exc:
                if self._logger is not None:
                    # Reutiliza el evento documentado radio.error: UDP es el
                    # sustituto de banco de pruebas para la capa de radio.
                    self._logger.error(
                        "radio.error",
                        transport="udp",
                        peer=f"{host}:{port}",
                        error=str(exc),
                    )

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        """Emite ``(frame, origin)`` desde un hilo lector interno."""

        self._start_reader()
        while True:
            item = self._queue.get()
            if item is None:
                return
            yield item

    def _start_reader(self) -> None:
        if self._reader is None:
            self._reader = threading.Thread(
                target=self._read_loop, name="udp-recv", daemon=True
            )
            self._reader.start()

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                data, address = self._sock.recvfrom(_RECV_BUFFER)
            except TimeoutError:
                continue
            except OSError:
                break
            self._queue.put((data, f"{address[0]}:{address[1]}"))
        self._queue.put(None)

    def close(self) -> None:
        """Detiene el hilo lector y cierra el socket limpiamente."""

        if self._closed.is_set():
            return
        self._closed.set()
        with contextlib.suppress(OSError):
            self._sock.close()
        if self._reader is not None:
            self._reader.join(timeout=1.0)


__all__ = ["UdpTransport", "parse_address"]
