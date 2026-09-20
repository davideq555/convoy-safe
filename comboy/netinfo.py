"""Utilidades de red del banco de pruebas.

La detección de la IP local existe por una razón concreta: ``transport.udp.peers``
es la dirección **del otro nodo**, no la propia. Eso significa que un nodo no
puede deducir de sí mismo a dónde mandar. Lo que sí puede hacer es anunciar en su
log dónde está escuchando, para que el otro lado sepa a dónde apuntar sin
adivinar ni mirar la IP a mano en cada máquina.
"""

from __future__ import annotations

import socket

#: Dirección usada solo para consultar la tabla de ruteo.
#:
#: ``connect()`` sobre un socket UDP **no envía ningún paquete**: solo fija la
#: interfaz de salida, y de ahí sale la IP local real. Se usa una dirección de
#: documentación (RFC 5737, TEST-NET-1) a propósito, para dejar claro que no
#: depende de que haya internet — que es justamente el escenario del proyecto.
_ROUTE_PROBE = "192.0.2.1"

#: Puerto discard (RFC 863). Irrelevante: no se transmite nada.
_PROBE_PORT = 9


def detect_local_ip() -> str | None:
    """Devuelve la IP local de la interfaz que usa la ruta por defecto.

    Devuelve ``None`` si no hay ruta utilizable (por ejemplo, una máquina sin
    red), en cuyo caso quien llame debe simplemente omitir el dato.

    No envía tráfico y no requiere privilegios.
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((_ROUTE_PROBE, _PROBE_PORT))
        return str(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()


__all__ = ["detect_local_ip"]
