"""Jeden wspólny, bezpieczny wątkowo bank danych dla GUI i protokołu."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .config import DataBlockSettings, DeviceSettings
from .register_map import DataArea, PointDefinition

AREA_ORDER = {area: index for index, area in enumerate(DataArea)}


class RegisterBankError(ValueError):
    pass


class UnknownRegisterError(RegisterBankError):
    pass


class ReadOnlyRegisterError(RegisterBankError):
    pass


class RegisterValueError(RegisterBankError):
    pass


class RegisterBank:
    def __init__(self, unit_id: int, blocks: list[DataBlockSettings] | None = None):
        self.unit_id = unit_id
        self._lock = RLock()
        self._revision = 0
        self._blocks: list[DataBlockSettings] = []
        self._points: dict[tuple[DataArea, int], PointDefinition] = {}
        self._values: dict[tuple[DataArea, int], int] = {}
        self.replace_blocks(blocks or [])

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def has_data(self) -> bool:
        with self._lock:
            return bool(self._points)

    def definitions(self, area: DataArea | None = None) -> list[PointDefinition]:
        with self._lock:
            return sorted(
                (p for p in self._points.values() if area is None or p.area == area),
                key=lambda p: (AREA_ORDER[p.area], p.address),
            )

    def snapshot(self) -> dict[tuple[DataArea, int], int]:
        with self._lock:
            return dict(self._values)

    def snapshot_with_revision(self):
        with self._lock:
            return dict(self._values), self._revision

    def export_blocks(self) -> list[DataBlockSettings]:
        with self._lock:
            return [replace(b, values=[self._values[(DataArea(b.area), a)] for a in range(b.start, b.start + b.count)]) for b in self._blocks]

    def replace_blocks(self, blocks: list[DataBlockSettings]) -> None:
        DeviceSettings(self.unit_id, blocks=blocks).validate()
        prepared = [replace(b, area=DataArea(b.area).value, values=b.complete_values()) for b in blocks]
        points, values = {}, {}
        for index, block in enumerate(prepared):
            area = DataArea(block.area)
            for offset, value in enumerate(block.values):
                address = block.start + offset
                key = area, address
                name = block.name if block.count == 1 else (f"{block.name} [{offset}]" if block.name else "")
                points[key] = PointDefinition(area, address, name, block.read_only or not area.writable, index)
                values[key] = value
        with self._lock:
            self._blocks, self._points, self._values = prepared, points, values
            self._revision += 1

    def _keys(self, area: DataArea, address: int, count: int) -> list[tuple[DataArea, int]]:
        if count < 1 or address < 0 or address + count > 65536:
            raise UnknownRegisterError("Zakres żądania poza przestrzenią adresową PDU")
        keys = [(area, a) for a in range(address, address + count)]
        if any(key not in self._points for key in keys):
            raise UnknownRegisterError(f"Niezdefiniowany adres w {area.label}: {address}, liczba {count}")
        return keys

    def read(self, area: DataArea, address: int, count: int = 1) -> list[int]:
        with self._lock:
            return [self._values[key] for key in self._keys(area, address, count)]

    def write(self, area: DataArea, address: int, values: list[int], *, operator: bool = False) -> None:
        with self._lock:
            keys = self._keys(area, address, len(values))
            for key, value in zip(keys, values):
                if not operator and self._points[key].read_only:
                    raise ReadOnlyRegisterError(f"Adres {key[1]} ({area.label}) jest tylko do odczytu")
                if not isinstance(value, int) or not 0 <= value <= (1 if area.is_bit else 65535):
                    raise RegisterValueError("Wartość poza zakresem typu danych")
            if any(self._values[key] != int(value) for key, value in zip(keys, values)):
                self._values.update((key, int(value)) for key, value in zip(keys, values))
                self._revision += 1

    def reset(self) -> None:
        with self._lock:
            self._values = dict.fromkeys(self._values, 0)
            self._revision += 1
