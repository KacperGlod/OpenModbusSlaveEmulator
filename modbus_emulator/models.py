"""Tabela punktów z mapy zdefiniowanej przez użytkownika."""

from time import monotonic

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor

from .register_bank import RegisterBank, RegisterBankError
from .register_map import DataArea, parse_value, to_signed_16


class RegisterTableModel(QAbstractTableModel):
    validation_error = pyqtSignal(str)
    HEADERS = ("Obszar", "Adres PDU", "Nazwa", "Dostęp", "Wartość", "HEX", "Signed 16")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: RegisterBank | None = None
        self._area: DataArea | None = None
        self._definitions = []
        self._snapshot = {}
        self._last_revision = -1
        self._changed_at = {}

    @property
    def bank(self):
        return self._bank

    def set_bank(self, bank):
        self.beginResetModel()
        self._bank = bank
        self._definitions = bank.definitions(self._area) if bank else []
        self._snapshot, self._last_revision = bank.snapshot_with_revision() if bank else ({}, -1)
        self._changed_at.clear()
        self.endResetModel()

    def set_area(self, area):
        self._area = DataArea(area) if area is not None else None
        self.set_bank(self._bank)

    def definition(self, row):
        return self._definitions[row] if 0 <= row < len(self._definitions) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._definitions)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if orientation == Qt.Orientation.Horizontal else section + 1
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self._bank is None:
            return None
        definition = self._definitions[index.row()]
        key = definition.area, definition.address
        value = self._snapshot[key]
        column = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return (definition.area.label, str(definition.address), definition.name,
                    "RO" if definition.read_only else "RW", str(value), f"0x{value:04X}",
                    "—" if definition.area.is_bit else str(to_signed_16(value)))[column]
        if role == Qt.ItemDataRole.BackgroundRole:
            if key in self._changed_at:
                return QBrush(QColor("#D9F7E8"))
        if role == Qt.ItemDataRole.ToolTipRole:
            return "Adresy PDU są liczone od 0. Operator może edytować również dane RO. Wartości: decimal, 0xHEX lub signed 16."
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 4 and self._bank:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 4 or role != Qt.ItemDataRole.EditRole or not self._bank:
            return False
        definition = self._definitions[index.row()]
        try:
            parsed = parse_value(str(value), definition.area)
            self._bank.write(definition.area, definition.address, [parsed], operator=True)
        except (ValueError, RegisterBankError) as error:
            self.validation_error.emit(str(error))
            return False
        self.refresh()
        return True

    def refresh(self):
        if not self._bank:
            return
        now = monotonic()
        repaint = set()
        if self._bank.revision != self._last_revision:
            snapshot, revision = self._bank.snapshot_with_revision()
            for key, value in snapshot.items():
                if self._snapshot.get(key) != value:
                    self._changed_at[key] = now
                    repaint.add(key)
            self._snapshot = snapshot
            self._last_revision = revision
        for key, changed_at in list(self._changed_at.items()):
            if now - changed_at >= 1.25:
                del self._changed_at[key]
                repaint.add(key)
        if not repaint:
            return
        for row, definition in enumerate(self._definitions):
            if (definition.area, definition.address) in repaint:
                self.dataChanged.emit(self.index(row, 4), self.index(row, 6))
