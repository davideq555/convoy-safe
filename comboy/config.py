"""Carga de configuración YAML (ver docs/02-arquitectura.md y doc 09).

Un nodo lee un único archivo YAML al arrancar. Si no se da ningún archivo (o el
archivo no existe), se usan los valores por defecto integrados para que el
programa siempre pueda arrancar.

La precedencia es **entorno real > ``.env`` > archivo YAML > valores por
defecto**. Las variables existen para que un mismo archivo sirva en varias
máquinas sin editarlo: lo que cambia de un nodo a otro (su id, su rol, a qué
peers le habla) se pasa por entorno o por el ``.env`` local. Ver :data:`ENV_VARS`.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .codes import Role, role_from_name
from .envfile import DEFAULT_ENV_FILE, ENV_FILE_VAR, load_env_file

VALID_TRANSPORT_KINDS = ("udp", "null", "lora")

#: Variables de entorno que sobrescriben la config, y la ruta que pisan dentro
#: del YAML. Son la forma de diferenciar nodos que comparten un mismo archivo.
ENV_VARS: dict[str, tuple[str, ...]] = {
    "COMBOY_NODE_ID": ("node", "id"),
    "COMBOY_NODE_ROLE": ("node", "role"),
    "COMBOY_TRANSPORT": ("transport", "kind"),
    "COMBOY_UDP_BIND": ("transport", "udp", "bind"),
    "COMBOY_UDP_PEERS": ("transport", "udp", "peers"),
    "COMBOY_LOG_LEVEL": ("log", "level"),
}


@dataclass(frozen=True)
class NodeConfig:
    """Identidad y rol de este nodo."""

    id: int = 1
    role: str = "follower"
    priority_order: int = 1

    @property
    def role_enum(self) -> Role:
        return role_from_name(self.role)


@dataclass(frozen=True)
class UdpConfig:
    """Ajustes del transporte UDP (banco de pruebas)."""

    bind: str = "0.0.0.0:45550"
    peers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TransportConfig:
    """Selección de transporte."""

    kind: str = "null"
    udp: UdpConfig = field(default_factory=UdpConfig)


@dataclass(frozen=True)
class SimulationConfig:
    """Simulación de pérdida/latencia que envuelve al transporte real."""

    enabled: bool = False
    delay_ms: float = 340.0
    loss: float = 0.10


@dataclass(frozen=True)
class LogConfig:
    """Comportamiento del log. ``path=None`` escribe a stderr."""

    path: str | None = None
    level: str = "info"


@dataclass(frozen=True)
class AudioConfig:
    """Ajustes de audio (en Fase 0 solo se usa TTS)."""

    wake_word: str = "atencion comboy"
    tts_voice: str = "es"
    half_duplex: bool = True


@dataclass(frozen=True)
class Config:
    """Configuración completa del nodo."""

    node: NodeConfig = field(default_factory=NodeConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    log: LogConfig = field(default_factory=LogConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)


def default_config() -> Config:
    """Devuelve la configuración por defecto (usada cuando no hay archivo)."""

    return Config()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _load_node(section: dict[str, Any]) -> NodeConfig:
    node = NodeConfig(
        id=int(section.get("id", 1)),
        role=str(section.get("role", "follower")),
        priority_order=int(section.get("priority_order", 1)),
    )
    role_from_name(node.role)  # falla rápido ante un rol inválido
    if not 1 <= node.id <= 255:
        raise ValueError(f"node.id debe estar en 1..255, se obtuvo {node.id}")
    return node


def _load_transport(section: dict[str, Any]) -> TransportConfig:
    kind = str(section.get("kind", "null")).strip().lower()
    if kind not in VALID_TRANSPORT_KINDS:
        raise ValueError(
            f"transport.kind debe ser uno de {VALID_TRANSPORT_KINDS}, se obtuvo {kind!r}"
        )
    udp_section = _section(section, "udp")
    peers = udp_section.get("peers", [])
    udp = UdpConfig(
        bind=str(udp_section.get("bind", "0.0.0.0:45550")),
        peers=[str(peer) for peer in peers] if isinstance(peers, list) else [],
    )
    return TransportConfig(kind=kind, udp=udp)


def _load_simulation(section: dict[str, Any]) -> SimulationConfig:
    loss = float(section.get("loss", 0.10))
    if not 0.0 <= loss <= 1.0:
        raise ValueError(f"simulation.loss debe estar en 0..1, se obtuvo {loss}")
    return SimulationConfig(
        enabled=bool(section.get("enabled", False)),
        delay_ms=float(section.get("delay_ms", 340.0)),
        loss=loss,
    )


def _load_log(section: dict[str, Any]) -> LogConfig:
    path = section.get("path")
    return LogConfig(
        path=str(path) if path else None,
        level=str(section.get("level", "info")),
    )


def _load_audio(section: dict[str, Any]) -> AudioConfig:
    return AudioConfig(
        wake_word=str(section.get("wake_word", "atencion comboy")),
        tts_voice=str(section.get("tts_voice", "es")),
        half_duplex=bool(section.get("half_duplex", True)),
    )


def _env_value(name: str, raw: str) -> Any:
    """Convierte el texto de una variable de entorno al tipo que espera el YAML."""

    if name == "COMBOY_NODE_ID":
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} debe ser un entero, se obtuvo {raw!r}") from exc
    if name == "COMBOY_UDP_PEERS":
        return [peer.strip() for peer in raw.split(",") if peer.strip()]
    return raw


def env_file_path() -> Path:
    """Ruta del ``.env`` a leer.

    Es :data:`~comboy.envfile.ENV_FILE_VAR` si está definida, y si no ``.env``
    en el directorio de trabajo.
    """

    override = os.environ.get(ENV_FILE_VAR)
    return Path(override) if override else Path(DEFAULT_ENV_FILE)


def effective_env() -> dict[str, str]:
    """El entorno real más las claves del ``.env`` que todavía no estén definidas.

    El entorno real gana: exportar una variable en la terminal pisa el archivo.
    """

    values = dict(os.environ)
    for key, value in load_env_file(env_file_path()).items():
        values.setdefault(key, value)
    return values


def apply_env_overrides(data: dict[str, Any] | None) -> dict[str, Any]:
    """Devuelve una copia de ``data`` con las variables de :data:`ENV_VARS` aplicadas.

    El entorno gana sobre el archivo. Una variable presente pero vacía se
    ignora: así ``COMBOY_UDP_PEERS=`` no borra la lista del YAML por accidente.
    """

    env = effective_env()
    result: dict[str, Any] = deepcopy(data) if data else {}
    for name, path in ENV_VARS.items():
        raw = env.get(name)
        if raw is None or raw.strip() == "":
            continue
        cursor = result
        for key in path[:-1]:
            child = cursor.get(key)
            if not isinstance(child, dict):
                child = {}
                cursor[key] = child
            cursor = child
        cursor[path[-1]] = _env_value(name, raw)
    return result


def config_from_mapping(data: dict[str, Any] | None) -> Config:
    """Construye un :class:`Config` a partir de un mapeo YAML ya parseado.

    Las variables de :data:`ENV_VARS` se aplican antes de construir, así que
    tienen la última palabra sobre el archivo.
    """

    data = apply_env_overrides(data)
    return Config(
        node=_load_node(_section(data, "node")),
        transport=_load_transport(_section(data, "transport")),
        simulation=_load_simulation(_section(data, "simulation")),
        log=_load_log(_section(data, "log")),
        audio=_load_audio(_section(data, "audio")),
    )


def load_config(path: str | Path | None) -> Config:
    """Carga un archivo de config YAML, con respaldo a los valores por defecto si falta.

    Una ruta ausente (``None``) o un archivo inexistente devuelven la
    configuración por defecto **con las variables de entorno ya aplicadas**. Un
    archivo presente pero mal formado lanza una excepción, porque ignorar en
    silencio una config rota es peor que fallar al arrancar.
    """

    if path is None:
        return config_from_mapping({})

    config_path = Path(path)
    if not config_path.exists():
        return config_from_mapping({})

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if data is not None and not isinstance(data, dict):
        raise ValueError(f"la raíz de la config debe ser un mapeo: {config_path}")

    return config_from_mapping(data)


__all__ = [
    "ENV_FILE_VAR",
    "ENV_VARS",
    "VALID_TRANSPORT_KINDS",
    "AudioConfig",
    "Config",
    "LogConfig",
    "NodeConfig",
    "SimulationConfig",
    "TransportConfig",
    "UdpConfig",
    "apply_env_overrides",
    "config_from_mapping",
    "default_config",
    "effective_env",
    "env_file_path",
    "load_config",
]
