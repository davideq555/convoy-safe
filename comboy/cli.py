"""Interfaz de línea de comandos: ``python -m comboy``.

Subcomandos:
    run       Corre el loop de recepción del nodo.
    send      Construye y transmite una trama de alerta.
    selftest  Autoprueba offline (CRC, round-trip del codec, rechazo de
              tramas corruptas, frase).

El subcomando ``text`` (nivel L1) deliberadamente no está implementado todavía.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence

from . import __version__
from .codes import (
    Confidence,
    Hazard,
    Lane,
    MsgType,
    Urgency,
    role_from_name,
)
from .config import Config, load_config
from .frame import AlertFrame
from .logging_setup import Logger
from .node import Node
from .phrase import build_phrase
from .transport import create_transport
from .tts import Speaker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m comboy",
        description="Alerta temprana de peligros para comboys de montaña (Fase 0 / L0).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_parser = subparsers.add_parser("run", help="corre el loop de recepción del nodo")
    run_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )

    send_parser = subparsers.add_parser("send", help="construye y envía una trama de alerta")
    send_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )
    send_parser.add_argument(
        "--hazard",
        required=True,
        help="nombre del código de peligro, p. ej. PIEDRAS",
    )
    send_parser.add_argument(
        "--lane", default="SIN_ESPECIFICAR", help="nombre del código de carril, p. ej. DERECHO"
    )
    send_parser.add_argument(
        "--dist-km", type=int, default=255, help="distancia declarada 0..15, o 255 desconocida"
    )
    send_parser.add_argument(
        "--urgency", default="PRECAUCION", help="nombre del código de urgencia, p. ej. PRECAUCION"
    )
    send_parser.add_argument(
        "--confidence", default="ALTA", help="nombre del código de confianza, p. ej. ALTA"
    )
    send_parser.add_argument(
        "--origin-id", type=int, default=None, help="sobrescribe el id de nodo configurado"
    )
    send_parser.add_argument(
        "--alert-id", type=lambda value: int(value, 0), default=None, help="id de alerta explícito"
    )

    subparsers.add_parser("selftest", help="corre las autopruebas offline (sin red)")

    return parser


def _make_logger(config: Config) -> Logger:
    return Logger(
        node_id=config.node.id,
        role=config.node.role,
        level=config.log.level,
        path=config.log.path,
    )


def _parse_hazard(value: str) -> Hazard:
    try:
        return Hazard[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"peligro desconocido: {value!r}") from exc


def _parse_lane(value: str) -> Lane:
    try:
        return Lane[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"carril desconocido: {value!r}") from exc


def _parse_urgency(value: str) -> Urgency:
    try:
        return Urgency[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"urgencia desconocida: {value!r}") from exc


def _parse_confidence(value: str) -> Confidence:
    try:
        return Confidence[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"confianza desconocida: {value!r}") from exc


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)
    try:
        node.run()
    finally:
        logger.close()
    return 0


def _send(args: argparse.Namespace) -> int:
    try:
        hazard = _parse_hazard(args.hazard)
        lane = _parse_lane(args.lane)
        urgency = _parse_urgency(args.urgency)
        confidence = _parse_confidence(args.confidence)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not 0 <= args.dist_km <= 255:
        print("error: --dist-km debe estar en 0..255", file=sys.stderr)
        return 2

    config = load_config(args.config)
    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)

    origin_id = args.origin_id if args.origin_id is not None else config.node.id
    if not 1 <= origin_id <= 255:
        print("error: --origin-id debe estar en 1..255", file=sys.stderr)
        node.close()
        logger.close()
        return 2

    alert_id = args.alert_id if args.alert_id is not None else random.getrandbits(32)
    frame = AlertFrame(
        msg_type=MsgType.ALERTA,
        alert_id=alert_id & 0xFFFFFFFF,
        origin_id=origin_id,
        origin_role=int(role_from_name(config.node.role)),
        hop=0,
        ttl=3,  # docs/03: el ttl se inicializa en 3
        hazard=int(hazard),
        lane=int(lane),
        dist_km=args.dist_km,
        urgency=int(urgency),
        confidence=int(confidence),
    )
    try:
        node.send_alert(frame)
    finally:
        node.close()
        logger.close()
    return 0


def _selftest_checks() -> list[tuple[str, bool, str]]:
    from .frame import CRC16_CCITT_FALSE_INIT, FRAME_SIZE, crc16_ccitt_false, decode

    checks: list[tuple[str, bool, str]] = []

    crc_vector = crc16_ccitt_false(b"123456789")
    checks.append(
        (
            "vector de verificación de crc16 b'123456789' -> 0x29B1",
            crc_vector == 0x29B1,
            f"se obtuvo 0x{crc_vector:04X}",
        )
    )
    checks.append(
        (
            "la constante init de crc16 es 0xFFFF",
            CRC16_CCITT_FALSE_INIT == 0xFFFF,
            f"se obtuvo 0x{CRC16_CCITT_FALSE_INIT:04X}",
        )
    )

    example = AlertFrame(
        alert_id=0x11223344,
        origin_id=1,
        origin_role=0,
        hop=0,
        ttl=3,
        hazard=Hazard.PIEDRAS,
        lane=Lane.DERECHO,
        dist_km=2,
        urgency=Urgency.PRECAUCION,
        confidence=Confidence.ALTA,
    )
    encoded = example.encode()
    checks.append(
        (
            "la trama codificada tiene 17 bytes",
            len(encoded) == FRAME_SIZE,
            f"se obtuvo {len(encoded)}",
        )
    )
    checks.append(("ida y vuelta encode/decode", decode(encoded) == example, ""))

    corrupt = bytearray(encoded)
    corrupt[16] ^= 0xFF
    checks.append(("la trama corrupta se rechaza", decode(bytes(corrupt)) is None, ""))
    short = b"\x00" * 16
    checks.append(("la trama corta se rechaza", decode(short) is None, ""))
    unknown_version = bytearray(encoded)
    unknown_version[0] = 2
    checks.append(("la versión desconocida se rechaza", decode(bytes(unknown_version)) is None, ""))

    expected_phrase = "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."
    phrase = build_phrase(example)
    checks.append(("frase de ejemplo de docs/06", phrase == expected_phrase, phrase))

    return checks


def _selftest(_args: argparse.Namespace) -> int:
    print(f"comboy-safe {__version__} autoprueba")
    failures = 0
    for name, ok, detail in _selftest_checks():
        status = "OK" if ok else "FALLA"
        suffix = f" ({detail})" if detail and not ok else ""
        print(f"  [{status}] {name}{suffix}")
        if not ok:
            failures += 1
    if failures:
        print(f"autoprueba FALLÓ ({failures} verificaciones)")
        return 1
    print("autoprueba OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "send":
        return _send(args)
    if args.command == "selftest":
        return _selftest(args)

    parser.print_help()
    return 2


__all__ = ["build_parser", "main"]
