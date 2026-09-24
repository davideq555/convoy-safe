"""convoy-safe: sistema de alerta temprana de peligros para convoys de montaña.

Fase 0 (nivel de banco de pruebas L0): mover una trama de 17 bytes por un
transporte, decodificarla, registrarla y pronunciarla. Sin flooding, sin
dedup, sin roster.

Convención de idioma: la prosa del código (docstrings, comentarios y textos de
ayuda) va en español. Los identificadores de código siguen en inglés. Los
nombres de eventos y claves de log, y las constantes de dominio del protocolo,
se rigen por ``docs/06-codigos-y-logs.md``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
