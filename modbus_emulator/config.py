"""Jawny format konfiguracji urządzeń i dowolnych zakresów adresowych."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import APPLICATION_NAME
from .register_map import DataArea

CONFIG_FORMAT = "modbus-slave-emulator"


class ConfigurationError(ValueError):
    pass


def _integer(value, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigurationError(f"{label}: wymagana liczba całkowita {minimum}..{maximum}")


def _object(value, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label}: wymagany obiekt JSON")
    if unknown := set(value) - allowed:
        raise ConfigurationError(f"{label}: nieznane pola: {', '.join(sorted(unknown))}")
    return value


@dataclass(slots=True)
class SerialSettings:
    port: str = ""
    baudrate: int = 19200
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout_seconds: float = 0.2
    local_echo: bool = False

    def validate(self, *, require_port: bool = True) -> None:
        if not isinstance(self.port, str) or (require_port and not self.port.strip()):
            raise ConfigurationError("Wybierz port szeregowy dla trybu RTU")
        _integer(self.baudrate, 1, 38400, "Prędkość RTU")
        _integer(self.bytesize, 7, 8, "Bity danych")
        if self.parity not in ("N", "E", "O"):
            raise ConfigurationError("Parzystość musi mieć wartość N, E albo O")
        _integer(self.stopbits, 1, 2, "Bity stopu")
        if type(self.timeout_seconds) not in (int, float) or not 0.01 <= self.timeout_seconds <= 10:
            raise ConfigurationError("Timeout portu musi należeć do zakresu 0.01..10 s")
        if type(self.local_echo) is not bool:
            raise ConfigurationError("Echo lokalne musi mieć wartość true/false")


@dataclass(slots=True)
class TcpSettings:
    host: str = "127.0.0.1"
    port: int = 1502

    def validate(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ConfigurationError("Adres nasłuchu TCP nie może być pusty")
        _integer(self.port, 1, 65535, "Port TCP")


@dataclass(slots=True)
class DataBlockSettings:
    area: str = DataArea.HOLDING_REGISTERS.value
    start: int = 0
    count: int = 1
    name: str = ""
    read_only: bool = False
    values: list[int] = field(default_factory=list)

    def validate(self) -> None:
        try:
            area = DataArea(self.area)
        except (ValueError, TypeError) as error:
            raise ConfigurationError("Nieznany obszar Modbus") from error
        _integer(self.start, 0, 65535, "Adres początkowy PDU")
        _integer(self.count, 1, 65536 - self.start, "Liczba adresów")
        if not isinstance(self.name, str) or type(self.read_only) is not bool:
            raise ConfigurationError("Nieprawidłowa nazwa lub dostęp zakresu")
        if not isinstance(self.values, list) or (self.values and len(self.values) != self.count):
            raise ConfigurationError("Lista wartości musi być pusta albo mieć długość równą liczbie adresów")
        for value in self.values:
            _integer(value, 0, 1 if area.is_bit else 65535, "Wartość")

    def complete_values(self) -> list[int]:
        return list(self.values) if self.values else [0] * self.count


@dataclass(slots=True)
class DeviceSettings:
    unit_id: int
    name: str = ""
    enabled: bool = True
    blocks: list[DataBlockSettings] = field(default_factory=list)

    def validate(self) -> None:
        _integer(self.unit_id, 1, 247, "Unit ID")
        if not isinstance(self.name, str) or type(self.enabled) is not bool:
            raise ConfigurationError("Nieprawidłowa nazwa lub dostępność urządzenia")
        if not isinstance(self.blocks, list):
            raise ConfigurationError("Zakresy muszą być listą")
        ends: dict[str, int] = {}
        for block in sorted(self.blocks, key=lambda item: (item.area, item.start)):
            block.validate()
            if block.start < ends.get(block.area, 0):
                raise ConfigurationError(f"ID {self.unit_id}: nakładające się zakresy {block.area}")
            ends[block.area] = block.start + block.count


@dataclass(slots=True)
class EmulatorSettings:
    format: str = CONFIG_FORMAT
    version: int = 1
    transport: str = "tcp"
    serial: SerialSettings = field(default_factory=SerialSettings)
    tcp: TcpSettings = field(default_factory=TcpSettings)
    devices: list[DeviceSettings] = field(default_factory=list)

    @classmethod
    def default(cls, device_count: int = 0) -> EmulatorSettings:
        _integer(device_count, 0, 247, "Liczba urządzeń")
        return cls(devices=[DeviceSettings(i, f"Urządzenie {i}") for i in range(1, device_count + 1)])

    def validate(self, *, require_runnable: bool = True) -> None:
        if self.format != CONFIG_FORMAT or type(self.version) is not int or self.version != 1:
            raise ConfigurationError("Nieobsługiwany format lub wersja konfiguracji")
        if self.transport not in ("rtu", "tcp"):
            raise ConfigurationError("Transport musi mieć wartość 'rtu' albo 'tcp'")
        self.serial.validate(require_port=require_runnable and self.transport == "rtu")
        self.tcp.validate()
        ids: set[int] = set()
        if not isinstance(self.devices, list):
            raise ConfigurationError("Urządzenia muszą być listą")
        for device in self.devices:
            device.validate()
            if device.unit_id in ids:
                raise ConfigurationError(f"Powtórzony Unit ID: {device.unit_id}")
            ids.add(device.unit_id)
        if require_runnable and not any(d.enabled and d.blocks for d in self.devices):
            raise ConfigurationError("Dodaj i włącz urządzenie z co najmniej jednym zakresem danych")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmulatorSettings:
        try:
            _object(data, {"format", "version", "transport", "serial", "tcp", "devices"}, "Konfiguracja")
            if data.get("format") != CONFIG_FORMAT:
                raise ConfigurationError(f"Plik nie jest konfiguracją {APPLICATION_NAME}")
            serial = SerialSettings(**_object(data.get("serial", {}), set(SerialSettings.__dataclass_fields__), "RTU"))
            tcp = TcpSettings(**_object(data.get("tcp", {}), set(TcpSettings.__dataclass_fields__), "TCP"))
            raw_devices = data.get("devices", [])
            if not isinstance(raw_devices, list):
                raise ConfigurationError("Urządzenia muszą być listą")
            devices = []
            for raw in raw_devices:
                raw = _object(raw, {"unit_id", "name", "enabled", "blocks"}, "Urządzenie")
                raw_blocks = raw.get("blocks", [])
                if not isinstance(raw_blocks, list):
                    raise ConfigurationError("Zakresy muszą być listą")
                blocks = [DataBlockSettings(**_object(b, set(DataBlockSettings.__dataclass_fields__), "Zakres")) for b in raw_blocks]
                devices.append(DeviceSettings(raw["unit_id"], raw.get("name", ""), raw.get("enabled", True), blocks))
            settings = cls(data["format"], data.get("version", 1), data.get("transport", "tcp"), serial, tcp, devices)
            settings.validate(require_runnable=False)
            return settings
        except ConfigurationError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ConfigurationError(f"Nieprawidłowa struktura konfiguracji: {error}") from error

    @classmethod
    def load(cls, path: Path) -> EmulatorSettings:
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"Nie udało się wczytać {path}: {error}") from error

    def save(self, path: Path) -> None:
        self.validate(require_runnable=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(path)
