"""Główne okno emulatora Modbus."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QCloseEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .config import (
    ConfigurationError,
    DeviceSettings,
    EmulatorSettings,
    SerialSettings,
    TcpSettings,
)
from . import __version__
from .dialogs import BlockDialog
from .models import RegisterTableModel
from .register_bank import RegisterBank
from .register_map import DataArea, READ_FUNCTION_CODES
from .server import EmulatorDevice, EmulatorEvent, MultiDeviceModbusServer


class EmulatorMainWindow(QMainWindow):
    def __init__(self, settings: EmulatorSettings, config_path: Path):
        super().__init__()
        self.config_path = config_path
        self.settings = settings
        self.server = MultiDeviceModbusServer()
        self.devices: dict[int, EmulatorDevice] = {}
        self.device_enabled: dict[int, bool] = {}
        self.server_expected_running = False
        self._updating_device_list = False
        self._request_count = 0

        self.setWindowTitle("Modbus Slave Emulator")
        self.resize(1280, 820)
        self.setMinimumSize(980, 650)
        self._build_ui()
        self._build_menu()
        self._replace_devices(settings)
        self._apply_settings_to_controls(settings)
        self._connect_signals()
        self._selected_device_changed()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(100)
        self.refresh_timer.timeout.connect(self._refresh_runtime_state)
        self.refresh_timer.start()

        self.statusBar().showMessage(f"Konfiguracja: {self.config_path}")

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 10, 12, 10)
        root_layout.setSpacing(10)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar(self))

        root_layout.addWidget(self._build_connection_box())

        vertical_splitter = QSplitter(Qt.Orientation.Vertical, root)
        vertical_splitter.addWidget(self._build_devices_and_registers())
        vertical_splitter.addWidget(self._build_log_box())
        vertical_splitter.setStretchFactor(0, 4)
        vertical_splitter.setStretchFactor(1, 1)
        vertical_splitter.setSizes([570, 190])
        root_layout.addWidget(vertical_splitter, 1)

        self.setStyleSheet(
            """
            QGroupBox {
                font-weight: bold;
                border: 1px solid #B8C2CC;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton { min-height: 30px; padding: 3px 10px; }
            QTableView { gridline-color: #D8DEE5; }
            """
        )

    def _build_connection_box(self) -> QGroupBox:
        box = QGroupBox("Transport")
        layout = QHBoxLayout(box)

        self.transport_combo = QComboBox()
        self.transport_combo.addItem("Modbus RTU", "rtu")
        self.transport_combo.addItem("Modbus TCP", "tcp")
        self.transport_combo.setFixedWidth(140)
        transport_field = QWidget()
        transport_layout = QHBoxLayout(transport_field)
        transport_layout.setContentsMargins(0, 0, 0, 0)
        transport_layout.setSpacing(4)
        transport_layout.addWidget(QLabel("Tryb:"))
        transport_layout.addWidget(self.transport_combo)
        self.connection_stack = QStackedWidget()
        self.connection_stack.addWidget(self._build_rtu_page())
        self.connection_stack.addWidget(self._build_tcp_page())

        configuration_layout = QHBoxLayout()
        configuration_layout.setContentsMargins(0, 0, 0, 0)
        configuration_layout.setSpacing(32)
        configuration_layout.addWidget(transport_field, 0, Qt.AlignmentFlag.AlignTop)
        configuration_layout.addWidget(self.connection_stack, 0, Qt.AlignmentFlag.AlignTop)
        configuration_layout.addStretch(1)
        layout.addLayout(configuration_layout, 1)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(separator)

        state_layout = QVBoxLayout()
        self.server_state_label = QLabel("ZATRZYMANY")
        self.server_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.server_state_label.setMinimumWidth(150)
        self._set_state_label(False, "ZATRZYMANY")
        self.start_button = QPushButton("Uruchom serwer")
        self.start_button.setMinimumWidth(170)
        state_layout.addWidget(self.server_state_label)
        state_layout.addWidget(self.start_button)
        layout.addLayout(state_layout)
        return box

    def _build_rtu_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setFixedWidth(145)
        self.refresh_ports_button = QPushButton("Odśwież")
        self.refresh_ports_button.setFixedWidth(90)
        refresh_button_height = max(20, self.port_combo.fontMetrics().height() + 6)
        self.refresh_ports_button.setStyleSheet(
            f"min-height: {refresh_button_height}px; max-height: {refresh_button_height}px; padding: 0 8px;"
        )

        self.baud_combo = QComboBox()
        for baudrate in (1200, 2400, 4800, 9600, 19200, 38400):
            self.baud_combo.addItem(str(baudrate), baudrate)
        self.baud_combo.setFixedWidth(100)

        self.bytesize_combo = QComboBox()
        for value in (7, 8):
            self.bytesize_combo.addItem(str(value), value)
        self.bytesize_combo.setFixedWidth(70)

        self.parity_combo = QComboBox()
        self.parity_combo.addItem("Brak", "N")
        self.parity_combo.addItem("Parzysta", "E")
        self.parity_combo.addItem("Nieparzysta", "O")
        self.parity_combo.setFixedWidth(135)

        self.stopbits_combo = QComboBox()
        for value in (1, 2):
            self.stopbits_combo.addItem(str(value), value)
        self.stopbits_combo.setFixedWidth(70)

        self.serial_timeout = QDoubleSpinBox()
        self.serial_timeout.setDecimals(2)
        self.serial_timeout.setRange(0.01, 10.0)
        self.serial_timeout.setSingleStep(0.05)
        self.serial_timeout.setSuffix(" s")
        self.serial_timeout.setFixedWidth(120)

        self.local_echo_check = QCheckBox("Echo lokalne")
        self.local_echo_check.setFixedWidth(110)

        control_alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        label_alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        layout.addWidget(QLabel("Port:"), 0, 0, label_alignment)
        layout.addWidget(self.port_combo, 0, 1, control_alignment)
        layout.addWidget(self.refresh_ports_button, 0, 2, control_alignment)

        layout.addWidget(QLabel("Parity:"), 1, 0, label_alignment)
        layout.addWidget(self.parity_combo, 1, 1, control_alignment)
        layout.addWidget(self.local_echo_check, 1, 2, 1, 2, control_alignment)

        layout.setColumnMinimumWidth(3, 40)
        layout.setColumnStretch(3, 0)

        layout.addWidget(QLabel("Baud:"), 0, 4, label_alignment)
        layout.addWidget(self.baud_combo, 0, 5, control_alignment)
        layout.addWidget(QLabel("Stop:"), 1, 4, label_alignment)
        layout.addWidget(self.stopbits_combo, 1, 5, control_alignment)

        layout.setColumnMinimumWidth(6, 40)
        layout.setColumnStretch(6, 0)

        layout.addWidget(QLabel("Bity:"), 0, 7, label_alignment)
        layout.addWidget(self.bytesize_combo, 0, 8, control_alignment)
        layout.addWidget(QLabel("Timeout:"), 1, 7, label_alignment)
        layout.addWidget(self.serial_timeout, 1, 8, control_alignment)
        return page

    def _build_tcp_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(6, 0, 6, 0)
        fields = QHBoxLayout()
        self.tcp_host_edit = QLineEdit()
        self.tcp_host_edit.setPlaceholderText("127.0.0.1 lub 0.0.0.0")
        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1, 65535)
        fields.addWidget(QLabel("Adres nasłuchu:"))
        fields.addWidget(self.tcp_host_edit, 1)
        fields.addWidget(QLabel("Port:"))
        fields.addWidget(self.tcp_port_spin)
        layout.addRow(fields)
        return page

    def _build_devices_and_registers(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        devices_box = QGroupBox("Urządzenia")
        devices_layout = QVBoxLayout(devices_box)
        self.device_count_label = QLabel()
        devices_layout.addWidget(self.device_count_label)

        self.device_list = QListWidget()
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_list.setAlternatingRowColors(True)
        devices_layout.addWidget(self.device_list, 1)

        device_buttons = QGridLayout()
        self.add_devices_button = QPushButton("Dodaj ID / zakres")
        self.rename_device_button = QPushButton("Zmień nazwę")
        self.remove_device_button = QPushButton("Usuń")
        self.enable_all_button = QPushButton("Włącz wszystkie")
        self.disable_all_button = QPushButton("Wyłącz wszystkie")
        device_buttons.addWidget(self.add_devices_button, 0, 0, 1, 2)
        device_buttons.addWidget(self.rename_device_button, 1, 0)
        device_buttons.addWidget(self.remove_device_button, 1, 1)
        device_buttons.addWidget(self.enable_all_button, 2, 0)
        device_buttons.addWidget(self.disable_all_button, 2, 1)
        devices_layout.addLayout(device_buttons)
        devices_box.setMinimumWidth(260)
        devices_box.setMaximumWidth(360)
        splitter.addWidget(devices_box)

        registers_box = QGroupBox("Dane Modbus — własna mapa adresów")
        registers_layout = QVBoxLayout(registers_box)

        toolbar = QHBoxLayout()
        self.selected_device_label = QLabel("Nie wybrano urządzenia")
        self.selected_device_label.setStyleSheet("font-size: 14px;")
        toolbar.addWidget(self.selected_device_label)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Obszar:"))
        self.area_filter = QComboBox()
        self.area_filter.addItem("Wszystkie", None)
        for area in DataArea:
            self.area_filter.addItem(area.label, area.value)
        toolbar.addWidget(self.area_filter)
        registers_layout.addLayout(toolbar)

        map_toolbar = QHBoxLayout()
        self.add_block_button = QPushButton("Dodaj zakres")
        self.edit_block_button = QPushButton("Edytuj zakres")
        self.remove_block_button = QPushButton("Usuń zakres")
        map_toolbar.addWidget(self.add_block_button)
        map_toolbar.addWidget(self.edit_block_button)
        map_toolbar.addWidget(self.remove_block_button)
        map_toolbar.addStretch()
        registers_layout.addLayout(map_toolbar)

        self.empty_map_label = QLabel()
        self.empty_map_label.setWordWrap(True)
        self.empty_map_label.setStyleSheet("color: #5B6570; padding: 8px;")
        registers_layout.addWidget(self.empty_map_label)

        self.register_model = RegisterTableModel(self)
        self.register_table = QTableView()
        self.register_table.setModel(self.register_model)
        self.register_table.setAlternatingRowColors(True)
        self.register_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.register_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.register_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.register_table.verticalHeader().setVisible(False)
        registers_layout.addWidget(self.register_table, 1)

        register_buttons = QHBoxLayout()
        self.reset_device_button = QPushButton("Wyzeruj wartości")
        self.copy_to_all_button = QPushButton("Kopiuj mapę i wartości do wszystkich")
        register_buttons.addWidget(self.reset_device_button)
        register_buttons.addWidget(self.copy_to_all_button)
        register_buttons.addStretch()
        hint = QLabel("Dwuklik w kolumnie „Wartość” edytuje dane, także RO.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5B6570;")
        registers_layout.addLayout(register_buttons)
        registers_layout.addWidget(hint)

        splitter.addWidget(registers_box)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 960])
        return splitter

    def _build_log_box(self) -> QGroupBox:
        box = QGroupBox("Ruch Modbus")
        layout = QVBoxLayout(box)
        toolbar = QHBoxLayout()
        self.request_count_label = QLabel("Żądania: 0")
        self.show_reads_check = QCheckBox("Pokaż odczyty FC01–FC04")
        self.show_writes_check = QCheckBox("Pokaż zapisy")
        self.show_writes_check.setChecked(True)
        self.clear_log_button = QPushButton("Wyczyść")
        toolbar.addWidget(self.request_count_label)
        toolbar.addStretch()
        toolbar.addWidget(self.show_reads_check)
        toolbar.addWidget(self.show_writes_check)
        toolbar.addWidget(self.clear_log_button)
        layout.addLayout(toolbar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background: #101820; color: #D6E2EA; "
            "font-family: Consolas, monospace; }"
        )
        layout.addWidget(self.log_view)
        return box

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Plik")

        self.new_action = QAction("Nowa konfiguracja…", self)
        self.open_action = QAction("Otwórz konfigurację…", self)
        self.save_action = QAction("Zapisz", self)
        self.save_as_action = QAction("Zapisz jako…", self)
        self.exit_action = QAction("Zamknij", self)

        self.save_action.setShortcut("Ctrl+S")
        self.open_action.setShortcut("Ctrl+O")

        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        help_menu = self.menuBar().addMenu("Pomoc")
        self.about_action = QAction("O emulatorze", self)
        help_menu.addAction(self.about_action)

    def _connect_signals(self) -> None:
        self.transport_combo.currentIndexChanged.connect(self._transport_changed)
        self.refresh_ports_button.clicked.connect(lambda _checked=False: self._refresh_ports())
        self.start_button.clicked.connect(self._start_stop_clicked)

        self.device_list.itemSelectionChanged.connect(self._selected_device_changed)
        self.device_list.itemChanged.connect(self._device_item_changed)
        self.add_devices_button.clicked.connect(self._add_devices)
        self.rename_device_button.clicked.connect(self._rename_device)
        self.remove_device_button.clicked.connect(self._remove_device)
        self.enable_all_button.clicked.connect(lambda: self._set_all_devices_enabled(True))
        self.disable_all_button.clicked.connect(lambda: self._set_all_devices_enabled(False))

        self.area_filter.currentIndexChanged.connect(self._area_changed)
        self.add_block_button.clicked.connect(self._add_block)
        self.edit_block_button.clicked.connect(self._edit_block)
        self.remove_block_button.clicked.connect(self._remove_block)
        self.register_table.selectionModel().selectionChanged.connect(self._update_map_buttons)
        self.reset_device_button.clicked.connect(self._reset_selected_device)
        self.copy_to_all_button.clicked.connect(self._copy_selected_to_all)
        self.register_model.validation_error.connect(self._show_validation_error)

        self.clear_log_button.clicked.connect(self.log_view.clear)
        self.new_action.triggered.connect(self._new_configuration)
        self.open_action.triggered.connect(self._open_configuration)
        self.save_action.triggered.connect(self._save_configuration)
        self.save_as_action.triggered.connect(self._save_configuration_as)
        self.exit_action.triggered.connect(self.close)
        self.about_action.triggered.connect(self._show_about)

    def _apply_settings_to_controls(self, settings: EmulatorSettings) -> None:
        mode_index = self.transport_combo.findData(settings.transport)
        self.transport_combo.setCurrentIndex(max(0, mode_index))
        self.connection_stack.setCurrentIndex(0 if settings.transport == "rtu" else 1)

        self._refresh_ports(settings.serial.port)
        if self.baud_combo.findData(settings.serial.baudrate) < 0:
            self.baud_combo.addItem(str(settings.serial.baudrate), settings.serial.baudrate)
        self._set_combo_data(self.baud_combo, settings.serial.baudrate)
        self._set_combo_data(self.bytesize_combo, settings.serial.bytesize)
        self._set_combo_data(self.parity_combo, settings.serial.parity)
        self._set_combo_data(self.stopbits_combo, settings.serial.stopbits)
        self.serial_timeout.setValue(settings.serial.timeout_seconds)
        self.local_echo_check.setChecked(settings.serial.local_echo)

        self.tcp_host_edit.setText(settings.tcp.host)
        self.tcp_port_spin.setValue(settings.tcp.port)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _refresh_ports(self, preferred_port: str | None = None) -> None:
        current = preferred_port
        if current is None:
            current = self.port_combo.currentText().strip()
        available = [port.device for port in list_ports.comports()]

        blocker = QSignalBlocker(self.port_combo)
        self.port_combo.clear()
        self.port_combo.addItems(available)
        if current and current not in available:
            self.port_combo.addItem(current)
        if current:
            self.port_combo.setCurrentText(current)
        elif available:
            self.port_combo.setCurrentIndex(0)
        del blocker

    def _transport_changed(self) -> None:
        self.connection_stack.setCurrentIndex(
            0 if self.transport_combo.currentData() == "rtu" else 1
        )

    def _replace_devices(self, settings: EmulatorSettings) -> None:
        self.devices.clear()
        self.device_enabled.clear()
        for device_settings in settings.devices:
            bank = RegisterBank(
                device_settings.unit_id,
                device_settings.blocks,
            )
            self.devices[device_settings.unit_id] = EmulatorDevice(
                unit_id=device_settings.unit_id,
                name=device_settings.name or f"Urządzenie {device_settings.unit_id}",
                bank=bank,
            )
            self.device_enabled[device_settings.unit_id] = device_settings.enabled
        self._rebuild_device_list()

    def _rebuild_device_list(self, select_unit_id: int | None = None) -> None:
        if select_unit_id is None:
            selected = self._selected_device()
            select_unit_id = selected.unit_id if selected else None

        self._updating_device_list = True
        blocker = QSignalBlocker(self.device_list)
        self.device_list.clear()
        selected_item = None
        for unit_id in sorted(self.devices):
            device = self.devices[unit_id]
            item = QListWidgetItem(f"ID {unit_id:03d} — {device.name}")
            item.setData(Qt.ItemDataRole.UserRole, unit_id)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if self.device_enabled.get(unit_id, True)
                else Qt.CheckState.Unchecked
            )
            if not self.device_enabled.get(unit_id, True):
                item.setForeground(QColor("#7A7A7A"))
            self.device_list.addItem(item)
            if unit_id == select_unit_id:
                selected_item = item
        del blocker
        self._updating_device_list = False

        if selected_item is not None:
            self.device_list.setCurrentItem(selected_item)
        elif self.device_list.count():
            self.device_list.setCurrentRow(0)
        else:
            self.register_model.set_bank(None)
        self._update_device_count()
        self._selected_device_changed()

    def _update_device_count(self) -> None:
        enabled = sum(1 for value in self.device_enabled.values() if value)
        self.device_count_label.setText(
            f"Skonfigurowane: {len(self.devices)}   Aktywne: {enabled}"
        )

    def _selected_device(self) -> EmulatorDevice | None:
        item = self.device_list.currentItem()
        if item is None:
            return None
        return self.devices.get(int(item.data(Qt.ItemDataRole.UserRole)))

    def _selected_device_changed(self) -> None:
        device = self._selected_device()
        self.register_model.set_bank(device.bank if device else None)
        self.selected_device_label.setText(
            f"ID {device.unit_id} — {device.name}"
            if device
            else "Nie wybrano urządzenia"
        )
        enabled = device is not None
        self.reset_device_button.setEnabled(enabled)
        self.copy_to_all_button.setEnabled(enabled and len(self.devices) > 1 and not self.server_expected_running)
        self.rename_device_button.setEnabled(enabled and not self.server_expected_running)
        self.remove_device_button.setEnabled(enabled and not self.server_expected_running)
        self._update_map_buttons()

    def _device_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating_device_list:
            return
        unit_id = int(item.data(Qt.ItemDataRole.UserRole))
        requested = item.checkState() == Qt.CheckState.Checked
        if self.server_expected_running:
            blocker = QSignalBlocker(self.device_list)
            item.setCheckState(
                Qt.CheckState.Checked
                if self.device_enabled.get(unit_id, True)
                else Qt.CheckState.Unchecked
            )
            del blocker
            self.statusBar().showMessage(
                "Zatrzymaj serwer przed zmianą dostępności urządzenia.", 4000
            )
            return
        self.device_enabled[unit_id] = requested
        self._rebuild_device_list(unit_id)

    def _add_devices(self) -> None:
        if self.server_expected_running:
            return
        suggested = 1
        while suggested in self.devices and suggested <= 247:
            suggested += 1
        text, accepted = QInputDialog.getText(
            self,
            "Dodawanie urządzeń",
            "Podaj Unit ID albo zakres, np. 11-50:",
            text=str(min(suggested, 247)),
        )
        if not accepted:
            return
        match = re.fullmatch(r"\s*(\d{1,3})(?:\s*[-:]\s*(\d{1,3}))?\s*", text)
        if not match:
            self._show_validation_error("Podaj pojedynczy ID albo zakres, np. 11-50.")
            return
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first > last:
            first, last = last, first
        if first < 1 or last > 247:
            self._show_validation_error("Unit ID musi należeć do zakresu 1..247.")
            return

        added = 0
        for unit_id in range(first, last + 1):
            if unit_id in self.devices:
                continue
            self.devices[unit_id] = EmulatorDevice(
                unit_id=unit_id,
                name=f"Urządzenie {unit_id}",
                bank=RegisterBank(unit_id),
            )
            self.device_enabled[unit_id] = True
            added += 1
        self._rebuild_device_list(first)
        self.statusBar().showMessage(f"Dodano urządzenia: {added}", 4000)

    def _rename_device(self) -> None:
        device = self._selected_device()
        if device is None or self.server_expected_running:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Nazwa urządzenia",
            f"Nazwa dla Unit ID {device.unit_id}:",
            text=device.name,
        )
        if accepted and name.strip():
            device.name = name.strip()
            self._rebuild_device_list(device.unit_id)

    def _remove_device(self) -> None:
        device = self._selected_device()
        if device is None or self.server_expected_running:
            return
        answer = QMessageBox.question(
            self,
            "Usuwanie urządzenia",
            f"Usunąć Unit ID {device.unit_id} z konfiguracji?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.devices.pop(device.unit_id, None)
        self.device_enabled.pop(device.unit_id, None)
        self._rebuild_device_list()

    def _set_all_devices_enabled(self, enabled: bool) -> None:
        if self.server_expected_running:
            return
        for unit_id in self.device_enabled:
            self.device_enabled[unit_id] = enabled
        self._rebuild_device_list()

    def _area_changed(self) -> None:
        self.register_model.set_area(self.area_filter.currentData())
        self._update_map_buttons()

    def _selected_block_index(self):
        definition = self.register_model.definition(self.register_table.currentIndex().row())
        return definition.block_index if definition else None

    def _update_map_buttons(self, *_args):
        device = self._selected_device()
        editable = device is not None and not self.server_expected_running
        selected = self._selected_block_index() is not None
        self.add_block_button.setEnabled(editable)
        self.edit_block_button.setEnabled(editable and selected)
        self.remove_block_button.setEnabled(editable and selected)
        self.empty_map_label.setVisible(self.register_model.rowCount() == 0)
        if device is None:
            self.empty_map_label.setText("Dodaj urządzenie przyciskiem „Dodaj ID / zakres”, następnie dodaj własne zakresy danych.")
        elif not device.bank.has_data:
            self.empty_map_label.setText("To urządzenie ma pustą mapę danych. Kliknij „Dodaj zakres”, aby zdefiniować adresy.")
        else:
            self.empty_map_label.setText("Brak adresów w wybranym obszarze. Zmień filtr lub dodaj zakres.")

    def _edit_device_block(self, block_index=None):
        device = self._selected_device()
        if device is None or self.server_expected_running:
            return
        blocks = device.bank.export_blocks()
        dialog = BlockDialog(blocks[block_index] if block_index is not None else None, self)
        if not dialog.exec():
            return
        if block_index is None:
            blocks.append(dialog.result_block)
        else:
            blocks[block_index] = dialog.result_block
        try:
            device.bank.replace_blocks(blocks)
        except ConfigurationError as error:
            self._show_validation_error(str(error))
            return
        self.register_model.set_bank(device.bank)
        self._update_map_buttons()

    def _add_block(self):
        self._edit_device_block()

    def _edit_block(self):
        index = self._selected_block_index()
        if index is not None:
            self._edit_device_block(index)

    def _remove_block(self):
        device = self._selected_device()
        index = self._selected_block_index()
        if device is None or index is None or self.server_expected_running:
            return
        if QMessageBox.question(self, "Usuwanie zakresu", "Usunąć cały zakres zawierający zaznaczony adres?") != QMessageBox.StandardButton.Yes:
            return
        blocks = device.bank.export_blocks()
        blocks.pop(index)
        device.bank.replace_blocks(blocks)
        self.register_model.set_bank(device.bank)
        self._update_map_buttons()

    def _reset_selected_device(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        answer = QMessageBox.question(
            self,
            "Zerowanie rejestrów",
            (
                f"Ustawić wszystkie wartości Unit ID {device.unit_id} na zero?"
            ),
        )
        if answer == QMessageBox.StandardButton.Yes:
            device.bank.reset()
            self.register_model.refresh()

    def _copy_selected_to_all(self) -> None:
        source = self._selected_device()
        if source is None or self.server_expected_running:
            return
        if QMessageBox.question(self, "Kopiowanie mapy", "Zastąpić mapy i wartości wszystkich pozostałych urządzeń mapą wybranego urządzenia?") != QMessageBox.StandardButton.Yes:
            return
        source_blocks = source.bank.export_blocks()
        copied = 0
        for unit_id, target in self.devices.items():
            if unit_id == source.unit_id:
                continue
            target.bank.replace_blocks(source_blocks)
            copied += 1
        self.statusBar().showMessage(
            f"Skopiowano mapę i wartości Unit ID {source.unit_id} do {copied} urządzeń.", 5000
        )

    def _collect_settings(self, *, validate: bool) -> EmulatorSettings:
        settings = EmulatorSettings(
            version=1,
            transport=str(self.transport_combo.currentData()),
            serial=SerialSettings(
                port=self.port_combo.currentText().strip(),
                baudrate=int(self.baud_combo.currentData()),
                bytesize=int(self.bytesize_combo.currentData()),
                parity=str(self.parity_combo.currentData()),
                stopbits=int(self.stopbits_combo.currentData()),
                timeout_seconds=float(self.serial_timeout.value()),
                local_echo=self.local_echo_check.isChecked(),
            ),
            tcp=TcpSettings(
                host=self.tcp_host_edit.text().strip(),
                port=self.tcp_port_spin.value(),
            ),
            devices=[
                DeviceSettings(
                    unit_id=unit_id,
                    name=self.devices[unit_id].name,
                    enabled=self.device_enabled.get(unit_id, True),
                    blocks=self.devices[unit_id].bank.export_blocks(),
                )
                for unit_id in sorted(self.devices)
            ],
        )
        if validate:
            settings.validate()
        return settings

    def _start_stop_clicked(self) -> None:
        if self.server_expected_running:
            self.start_button.setEnabled(False)
            self.server_state_label.setText("ZATRZYMYWANIE…")
            threading.Thread(target=self.server.stop, daemon=True).start()
            return

        try:
            settings = self._collect_settings(validate=True)
            self.server.start(settings, list(self.devices.values()))
        except (ConfigurationError, RuntimeError) as error:
            self._show_validation_error(str(error))
            return

        self.settings = settings
        self.server_expected_running = True
        self._set_configuration_enabled(False)
        self.start_button.setText("Zatrzymaj serwer")
        self.server_state_label.setText("URUCHAMIANIE…")
        self.server_state_label.setStyleSheet(
            "font-weight: bold; color: #9A6500; padding: 7px; "
            "background: #FFF3CD; border-radius: 4px;"
        )

    def _set_configuration_enabled(self, enabled: bool) -> None:
        self.transport_combo.setEnabled(enabled)
        self.connection_stack.setEnabled(enabled)
        self.add_devices_button.setEnabled(enabled)
        self.enable_all_button.setEnabled(enabled)
        self.disable_all_button.setEnabled(enabled)
        self.rename_device_button.setEnabled(enabled and self._selected_device() is not None)
        self.remove_device_button.setEnabled(enabled and self._selected_device() is not None)
        self.copy_to_all_button.setEnabled(enabled and self._selected_device() is not None and len(self.devices) > 1)
        self.new_action.setEnabled(enabled)
        self.open_action.setEnabled(enabled)
        self._update_map_buttons()

    def _refresh_runtime_state(self) -> None:
        self.register_model.refresh()
        for event in self.server.drain_events():
            self._handle_server_event(event)

    def _handle_server_event(self, event: EmulatorEvent) -> None:
        if event.kind == "started":
            self.server_expected_running = True
            self._set_state_label(True, "DZIAŁA")
            self.start_button.setText("Zatrzymaj serwer")
            self.start_button.setEnabled(True)
            self._append_log(event)
            return

        if event.kind == "stopped":
            self.server_expected_running = False
            self._set_state_label(False, "ZATRZYMANY")
            self.start_button.setText("Uruchom serwer")
            self.start_button.setEnabled(True)
            self._set_configuration_enabled(True)
            self._append_log(event)
            return

        if event.kind == "error":
            self._append_log(event)
            self.statusBar().showMessage(event.message, 10000)
            return

        if event.kind == "request":
            self._request_count += 1
            self.request_count_label.setText(f"Żądania: {self._request_count}")
            is_read = event.function_code in READ_FUNCTION_CODES
            if (is_read and self.show_reads_check.isChecked()) or (
                not is_read and self.show_writes_check.isChecked()
            ):
                self._append_log(event)
            return

        self._append_log(event)

    def _append_log(self, event: EmulatorEvent) -> None:
        timestamp = event.created_at.strftime("%H:%M:%S.%f")[:-3]
        prefix = {
            "error": "BŁĄD",
            "warning": "UWAGA",
            "started": "START",
            "stopped": "STOP",
            "request": "MODBUS",
        }.get(event.kind, event.kind.upper())
        self.log_view.appendPlainText(f"[{timestamp}] {prefix}: {event.message}")

    def _set_state_label(self, running: bool, text: str) -> None:
        self.server_state_label.setText(text)
        if running:
            self.server_state_label.setStyleSheet(
                "font-weight: bold; color: #0A5C36; padding: 7px; "
                "background: #D9F7E8; border-radius: 4px;"
            )
        else:
            self.server_state_label.setStyleSheet(
                "font-weight: bold; color: #8B1E1E; padding: 7px; "
                "background: #FBE3E3; border-radius: 4px;"
            )

    def _show_validation_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        QMessageBox.warning(self, "Nieprawidłowa konfiguracja", message)

    def _save_configuration(self) -> None:
        try:
            self.settings = self._collect_settings(validate=False)
            self.settings.save(self.config_path)
        except (OSError, ConfigurationError) as error:
            QMessageBox.critical(self, "Błąd zapisu", str(error))
            return
        self.statusBar().showMessage(f"Zapisano: {self.config_path}", 5000)

    def _save_configuration_as(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Zapisz konfigurację emulatora",
            str(self.config_path),
            "Konfiguracja JSON (*.json)",
        )
        if not path:
            return
        self.config_path = Path(path)
        self._save_configuration()

    def _open_configuration(self) -> None:
        if self.server_expected_running:
            QMessageBox.information(
                self,
                "Serwer działa",
                "Zatrzymaj serwer przed wczytaniem innej konfiguracji.",
            )
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Otwórz konfigurację emulatora",
            str(self.config_path.parent),
            "Konfiguracja JSON (*.json)",
        )
        if not path:
            return
        try:
            settings = EmulatorSettings.load(Path(path))
        except ConfigurationError as error:
            QMessageBox.critical(self, "Błąd konfiguracji", str(error))
            return

        self.config_path = Path(path)
        self.settings = settings
        self._replace_devices(settings)
        self._apply_settings_to_controls(settings)
        self.statusBar().showMessage(f"Wczytano: {self.config_path}", 5000)

    def _new_configuration(self):
        if self.server_expected_running:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Nowa pusta konfiguracja", str(self.config_path.parent / "new-emulator.json"), "Konfiguracja JSON (*.json)")
        if not path:
            return
        settings = EmulatorSettings.default()
        try:
            settings.save(Path(path))
        except (OSError, ConfigurationError) as error:
            QMessageBox.critical(self, "Błąd zapisu", str(error))
            return
        self.config_path = Path(path)
        self.settings = settings
        self._replace_devices(settings)
        self._apply_settings_to_controls(settings)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "O emulatorze",
            (
                f"<b>Modbus Slave Emulator {__version__}</b><br><br>"
                "Wielourządzeniowy serwer Modbus RTU/TCP dla Unit ID 1–247.<br>"
                "Własne zakresy coils, discrete inputs, holding registers i input registers."
            ),
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.server_expected_running or self.server.is_active:
            self.server.stop(timeout_seconds=3.0)
        if self.server.is_active:
            QMessageBox.warning(self, "Zatrzymywanie serwera", "Serwer nadal się zatrzymuje. Spróbuj ponownie zamknąć okno.")
            event.ignore()
            return
        try:
            self.settings = self._collect_settings(validate=False)
            self.settings.save(self.config_path)
        except (OSError, ConfigurationError) as error:
            answer = QMessageBox.question(self, "Błąd zapisu", f"{error}\n\nZamknąć bez zapisywania?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
