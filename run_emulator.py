"""Uruchom emulator z czytelnym komunikatem o brakujących zależnościach."""

from __future__ import annotations

import sys


try:
    from modbus_emulator.main import main
except ModuleNotFoundError as error:
    if error.name and error.name.split(".")[0] in {"PyQt6", "pymodbus", "serial"}:
        print(
            "Brakuje zależności emulatora. Uruchom:\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    raise


if __name__ == "__main__":
    raise SystemExit(main())
