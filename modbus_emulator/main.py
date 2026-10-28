"""Punkt wejścia niezależnego emulatora Modbus Slave."""

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .config import ConfigurationError, EmulatorSettings
from .gui import EmulatorMainWindow


def default_config_path() -> Path:
    # EXE zapisuje ustawienia obok pliku wykonywalnego, poza katalogiem rozpakowania.
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return root / "emulator.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Uniwersalny emulator Modbus Slave RTU/TCP")
    parser.add_argument("--config", type=Path, default=default_config_path(), help="Ścieżka konfiguracji JSON")
    parser.add_argument("--devices", type=int, default=0, help="Liczba pustych urządzeń przy pierwszym uruchomieniu (0..247)")
    arguments = parser.parse_args()
    if not 0 <= arguments.devices <= 247:
        parser.error("--devices musi należeć do zakresu 0..247")
    application = QApplication(sys.argv)
    application.setApplicationName("Modbus Slave Emulator")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("Modbus Slave Emulator")
    try:
        settings = EmulatorSettings.load(arguments.config) if arguments.config.exists() else EmulatorSettings.default(arguments.devices)
    except ConfigurationError as error:
        QMessageBox.critical(None, "Błąd konfiguracji", str(error))
        return 1
    window = EmulatorMainWindow(settings, arguments.config)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
