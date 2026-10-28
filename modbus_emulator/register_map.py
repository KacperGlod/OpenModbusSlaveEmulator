"""Typy obszarów Modbus. Mapa adresów pochodzi wyłącznie od użytkownika."""

from dataclasses import dataclass
from enum import Enum


class DataArea(str, Enum):
    COILS = "coils"
    DISCRETE_INPUTS = "discrete_inputs"
    HOLDING_REGISTERS = "holding_registers"
    INPUT_REGISTERS = "input_registers"

    @property
    def label(self) -> str:
        return AREA_LABELS[self]

    @property
    def is_bit(self) -> bool:
        return self in {self.COILS, self.DISCRETE_INPUTS}

    @property
    def writable(self) -> bool:
        return self in {self.COILS, self.HOLDING_REGISTERS}


AREA_LABELS = {
    DataArea.COILS: "Coils (0/1)",
    DataArea.DISCRETE_INPUTS: "Discrete inputs (0/1)",
    DataArea.HOLDING_REGISTERS: "Holding registers (16 bit)",
    DataArea.INPUT_REGISTERS: "Input registers (16 bit)",
}

FUNCTION_AREAS = {
    1: DataArea.COILS, 2: DataArea.DISCRETE_INPUTS,
    3: DataArea.HOLDING_REGISTERS, 4: DataArea.INPUT_REGISTERS,
    5: DataArea.COILS, 6: DataArea.HOLDING_REGISTERS,
    15: DataArea.COILS, 16: DataArea.HOLDING_REGISTERS,
    22: DataArea.HOLDING_REGISTERS, 23: DataArea.HOLDING_REGISTERS,
}
READ_FUNCTION_CODES = {1, 2, 3, 4}


@dataclass(frozen=True, slots=True)
class PointDefinition:
    area: DataArea
    address: int
    name: str
    read_only: bool
    block_index: int


def parse_value(text: str, area: DataArea) -> int:
    text = text.strip()
    value = int(text, 16) if text.lower().startswith(("0x", "+0x", "-0x")) else int(text, 10)
    if not area.is_bit and -32768 <= value < 0:
        value += 65536
    maximum = 1 if area.is_bit else 65535
    if not 0 <= value <= maximum:
        raise ValueError(f"Wartość musi należeć do zakresu 0..{maximum}")
    return value


def to_signed_16(value: int) -> int:
    return value if value < 32768 else value - 65536
