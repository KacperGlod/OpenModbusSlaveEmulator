"""Edytor zakresu adresowego użytkownika."""

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QLineEdit, QMessageBox, QSpinBox,
)

from .config import ConfigurationError, DataBlockSettings
from .register_map import DataArea, parse_value


class BlockDialog(QDialog):
    def __init__(self, block: DataBlockSettings | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edytuj zakres" if block else "Dodaj zakres")
        self.setMinimumWidth(460)
        self.block = block
        self.result_block = None
        layout = QFormLayout(self)
        self.area_combo = QComboBox()
        for area in DataArea:
            self.area_combo.addItem(area.label, area.value)
        self.area_combo.setCurrentIndex(self.area_combo.findData(block.area if block else DataArea.HOLDING_REGISTERS.value))
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 65535)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 65536)
        self.name_edit = QLineEdit(block.name if block else "")
        self.value_edit = QLineEdit("" if block else "0")
        self.value_edit.setPlaceholderText("Puste = zachowaj wartości; nowe adresy = 0" if block else "0, 123, 0x1234 lub -1")
        self.read_only_check = QCheckBox("Zablokuj zapis przez klienta Modbus")
        self.read_only_check.setChecked(block.read_only if block else False)
        layout.addRow("Obszar:", self.area_combo)
        layout.addRow("Adres początkowy PDU:", self.start_spin)
        layout.addRow("Liczba adresów:", self.count_spin)
        layout.addRow("Nazwa zakresu (opcjonalna):", self.name_edit)
        layout.addRow("Wartość dla całego zakresu:", self.value_edit)
        layout.addRow(self.read_only_check)
        hint = QLabel("Adresy 0..65535, bez prefiksów 0xxxx/1xxxx/3xxxx/4xxxx.\nDane RO można zmieniać jako operator w tabeli.")
        hint.setWordWrap(True)
        layout.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.start_spin.valueChanged.connect(lambda start: self.count_spin.setMaximum(65536 - start))
        self.area_combo.currentIndexChanged.connect(self._area_changed)
        self.start_spin.setValue(block.start if block else 0)
        self.count_spin.setValue(block.count if block else 10)
        self._area_changed()

    def _area_changed(self):
        writable = DataArea(self.area_combo.currentData()).writable
        self.read_only_check.setEnabled(writable)

    def accept(self):
        area = DataArea(self.area_combo.currentData())
        count = self.count_spin.value()
        try:
            if self.value_edit.text().strip():
                values = [parse_value(self.value_edit.text(), area)] * count
            elif self.block:
                old = self.block.complete_values()
                values = old[:count] + [0] * max(0, count - len(old))
            else:
                values = [0] * count
            block = DataBlockSettings(area.value, self.start_spin.value(), count, self.name_edit.text().strip(),
                                     self.read_only_check.isChecked() and area.writable, values)
            block.validate()
        except (ValueError, ConfigurationError) as error:
            QMessageBox.warning(self, "Nieprawidłowy zakres", str(error))
            return
        self.result_block = block
        super().accept()
