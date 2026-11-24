from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

from modbus_emulator.config import ConfigurationError, DataBlockSettings, DeviceSettings, EmulatorSettings, TcpSettings
from modbus_emulator.dialogs import BlockDialog
from modbus_emulator.gui import EmulatorMainWindow
from modbus_emulator.register_bank import ReadOnlyRegisterError, RegisterBank, RegisterValueError, UnknownRegisterError
from modbus_emulator.register_map import DataArea, parse_value
from modbus_emulator.server import EmulatorDevice, MultiDeviceModbusServer


def block(area="holding_registers", start=0, count=3, **kwargs):
    return DataBlockSettings(area, start, count, **kwargs)


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


class ConfigurationTests(unittest.TestCase):
    def test_default_is_empty_and_can_be_saved(self):
        settings = EmulatorSettings.default()
        self.assertEqual(settings.devices, [])
        settings.validate(require_runnable=False)
        with self.assertRaises(ConfigurationError):
            settings.validate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            settings.save(path)
            self.assertEqual(EmulatorSettings.load(path), settings)

    def test_new_devices_have_no_predefined_data(self):
        self.assertTrue(all(not device.blocks for device in EmulatorSettings.default(10).devices))

    def test_round_trip_all_areas(self):
        settings = EmulatorSettings(devices=[DeviceSettings(7, "Test", blocks=[block(a.value, 11, 2, values=[0, 1]) for a in DataArea])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            settings.save(path)
            loaded = EmulatorSettings.load(path)
            self.assertEqual(loaded, settings)
            loaded.validate()

    def test_unrelated_format_and_unknown_fields_are_rejected(self):
        for data in ({"version": 1, "devices": []}, {"format": "other", "devices": []},
                     {**EmulatorSettings.default().to_dict(), "unexpected": 1}):
            with self.subTest(data=data), self.assertRaises(ConfigurationError):
                EmulatorSettings.from_dict(data)

    def test_malformed_json_structures_are_rejected(self):
        base = EmulatorSettings.default().to_dict()
        cases = [[], None, {**base, "devices": {}}, {**base, "serial": []},
                 {**base, "devices": [{"unit_id": 1, "blocks": [None]}]},
                 {**base, "devices": [{"unit_id": "1"}]},
                 {**base, "devices": [{"unit_id": 1, "enabled": "false"}]},
                 {**base, "devices": [{"unit_id": 1, "blocks": [{"area": [], "start": 0}]}]},
                 {**base, "tcp": {"port": "502"}}]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ConfigurationError):
                EmulatorSettings.from_dict(data)

    def test_overlaps_rejected_within_one_area(self):
        settings = EmulatorSettings(devices=[DeviceSettings(1, blocks=[block(start=2), block(start=4)])])
        with self.assertRaises(ConfigurationError):
            settings.validate()

    def test_same_address_is_allowed_in_different_areas(self):
        EmulatorSettings(devices=[DeviceSettings(1, blocks=[block(a.value) for a in DataArea])]).validate()

    def test_duplicate_ids_and_invalid_ranges_rejected(self):
        with self.assertRaises(ConfigurationError):
            EmulatorSettings(devices=[DeviceSettings(1), DeviceSettings(1)]).validate(require_runnable=False)
        for entry in (block(start=-1), block(start=65535, count=2), block(count=0),
                      block(values=[1]), block(values=[1, 2, 65536]), block("coils", values=[0, 1, 2])):
            with self.subTest(entry=entry), self.assertRaises(ConfigurationError):
                entry.validate()


class BankTests(unittest.TestCase):
    def test_empty_bank_rejects_every_address(self):
        bank = RegisterBank(1)
        self.assertEqual(bank.snapshot(), {})
        for area in DataArea:
            with self.assertRaises(UnknownRegisterError):
                bank.read(area, 0)

    def test_same_address_independent_per_area_and_device(self):
        first = RegisterBank(1, [block(a.value) for a in DataArea])
        second = RegisterBank(2, first.export_blocks())
        first.write(DataArea.HOLDING_REGISTERS, 0, [123])
        first.write(DataArea.COILS, 0, [1])
        self.assertEqual(second.read(DataArea.HOLDING_REGISTERS, 0), [0])
        self.assertEqual(first.read(DataArea.INPUT_REGISTERS, 0), [0])
        self.assertEqual(first.read(DataArea.DISCRETE_INPUTS, 0), [0])

    def test_writes_are_atomic_for_gaps_read_only_and_values(self):
        bank = RegisterBank(1, [block(count=2), block(start=2, count=1, read_only=True)])
        for address, values, error in ((0, [1, 2, 3], ReadOnlyRegisterError),
                                       (0, [1, 65536], RegisterValueError),
                                       (3, [1], UnknownRegisterError)):
            with self.assertRaises(error):
                bank.write(DataArea.HOLDING_REGISTERS, address, values)
            self.assertEqual(bank.read(DataArea.HOLDING_REGISTERS, 0, 3), [0, 0, 0])

    def test_operator_can_set_input_data_and_reset_every_address(self):
        bank = RegisterBank(17, [block(a.value, 19, 1) for a in DataArea])
        for area in DataArea:
            bank.write(area, 19, [1], operator=True)
        bank.reset()
        self.assertTrue(all(value == 0 for value in bank.snapshot().values()))

    def test_export_and_input_blocks_do_not_share_mutable_values(self):
        entry = block(values=[1, 2, 3])
        bank = RegisterBank(1, [entry])
        entry.values[0] = 10
        exported = bank.export_blocks()
        exported[0].values[0] = 20
        self.assertEqual(bank.read(DataArea.HOLDING_REGISTERS, 0), [1])

    def test_value_parser_decimal_hex_and_signed(self):
        area = DataArea.HOLDING_REGISTERS
        for text, expected in (("0010", 10), ("0x10", 16), ("-1", 65535), ("-32768", 32768)):
            self.assertEqual(parse_value(text, area), expected)
        for text in ("-32769", "65536", "", "1.5"):
            with self.assertRaises(ValueError):
                parse_value(text, area)
        with self.assertRaises(ValueError):
            parse_value("2", DataArea.COILS)


class TcpTests(unittest.TestCase):
    def setUp(self):
        blocks = [block(a.value, 17, 24) for a in DataArea]
        blocks += [block("holding_registers", 100, 2, read_only=True),
                   block("holding_registers", 102, 2), block("coils", 100, 2, read_only=True),
                   block("holding_registers", 65535, 1), block("coils", 65535, 1)]
        self.settings = EmulatorSettings(tcp=TcpSettings(port=free_port()), devices=[DeviceSettings(i, blocks=blocks) for i in range(1, 51)])
        self.settings.devices.append(DeviceSettings(51, enabled=False, blocks=blocks))
        self.devices = [EmulatorDevice(d.unit_id, d.name, RegisterBank(d.unit_id, d.blocks)) for d in self.settings.devices]
        self.server = MultiDeviceModbusServer()
        self.addCleanup(self.server.stop)
        self.server.start(self.settings, self.devices)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = self.server.drain_events()
            errors = [event.message for event in events if event.kind == "error"]
            if errors:
                self.fail(str(errors))
            if self.server.is_running:
                break
            time.sleep(0.01)
        self.assertTrue(self.server.is_running)
        self.client = ModbusTcpClient("127.0.0.1", port=self.settings.tcp.port, timeout=0.15, retries=0)
        self.addCleanup(self.client.close)
        self.assertTrue(self.client.connect())

    def assert_ok(self, response):
        self.assertFalse(response.isError(), response)
        return response

    def test_all_four_areas_and_unit_50_are_independent(self):
        self.assert_ok(self.client.write_registers(17, [111, 222], device_id=50))
        self.assertEqual(self.assert_ok(self.client.read_holding_registers(17, count=2, device_id=50)).registers, [111, 222])
        self.assertEqual(self.assert_ok(self.client.read_holding_registers(17, count=2, device_id=49)).registers, [0, 0])
        self.assert_ok(self.client.write_coil(17, True, device_id=50))
        self.assertTrue(self.assert_ok(self.client.read_coils(17, count=1, device_id=50)).bits[0])
        self.assertFalse(self.assert_ok(self.client.read_discrete_inputs(17, count=1, device_id=50)).bits[0])
        self.assertEqual(self.assert_ok(self.client.read_input_registers(17, count=1, device_id=50)).registers, [0])

    def test_multiple_coils_across_byte_and_word_boundaries(self):
        values = [i % 3 == 0 for i in range(24)]
        self.assert_ok(self.client.write_coils(17, values, device_id=1))
        self.assertEqual(self.assert_ok(self.client.read_coils(17, count=24, device_id=1)).bits[:24], values)
        self.assertEqual(self.devices[0].bank.read(DataArea.COILS, 17, 24), [int(v) for v in values])

    def test_operator_updates_are_visible_in_all_areas(self):
        for area in DataArea:
            self.devices[0].bank.write(area, 17, [1], operator=True)
        for method in (self.client.read_coils, self.client.read_discrete_inputs):
            self.assertTrue(self.assert_ok(method(17, count=1, device_id=1)).bits[0])
        for method in (self.client.read_holding_registers, self.client.read_input_registers):
            self.assertEqual(self.assert_ok(method(17, count=1, device_id=1)).registers, [1])

    def test_sparse_and_bit_padding_addresses_are_not_exposed(self):
        for method, address, count in ((self.client.read_coils, 16, 1), (self.client.read_coils, 40, 2),
                                       (self.client.read_coils, 41, 1), (self.client.read_discrete_inputs, 41, 1),
                                       (self.client.read_holding_registers, 41, 1), (self.client.read_input_registers, 100, 1)):
            with self.subTest(address=address, method=method):
                response = method(address, count=count, device_id=1)
                self.assertTrue(response.isError())
                self.assertEqual(response.exception_code, 2)

    def test_read_only_registers_and_coils_reject_atomic_writes(self):
        for response in (self.client.write_register(100, 10, device_id=1),
                         self.client.write_registers(99, [10, 20, 30], device_id=1),
                         self.client.write_coils(100, [True, True], device_id=1)):
            self.assertTrue(response.isError())
            self.assertEqual(response.exception_code, 2)
        self.assertEqual(self.assert_ok(self.client.read_holding_registers(100, count=4, device_id=1)).registers, [0] * 4)

    def test_maximum_address_and_value(self):
        self.assert_ok(self.client.write_register(65535, 65535, device_id=1))
        self.assertEqual(self.assert_ok(self.client.read_holding_registers(65535, count=1, device_id=1)).registers, [65535])
        self.assert_ok(self.client.write_coil(65535, True, device_id=1))
        self.assertTrue(self.assert_ok(self.client.read_coils(65535, count=1, device_id=1)).bits[0])

    def test_mask_write_and_combined_read_write(self):
        self.assert_ok(self.client.write_register(17, 0x1234, device_id=1))
        self.assert_ok(self.client.mask_write_register(address=17, and_mask=0xFF00, or_mask=0x0056, device_id=1))
        self.assertEqual(self.assert_ok(self.client.read_holding_registers(17, count=1, device_id=1)).registers, [0x1256])
        response = self.client.readwrite_registers(read_address=17, read_count=2, write_address=17, values=[9, 8], device_id=1)
        self.assertEqual(self.assert_ok(response).registers, [9, 8])

    def test_unconfigured_and_disabled_unit_ids_do_not_respond(self):
        for unit_id in (51, 99):
            with self.assertLogs("pymodbus.logging", level="ERROR"), self.assertRaises(ModbusIOException):
                self.client.read_holding_registers(17, count=1, device_id=unit_id)

    def test_request_counter_logs_one_event_per_wire_request(self):
        self.server.drain_events()
        self.assert_ok(self.client.write_register(17, 7, device_id=1))
        self.assert_ok(self.client.read_holding_registers(17, count=1, device_id=1))
        events = [event for event in self.server.drain_events() if event.kind == "request"]
        self.assertEqual([e.function_code for e in events], [6, 3])

    def test_stop_and_restart(self):
        self.client.close()
        self.server.stop()
        self.assertFalse(self.server.is_active)
        self.server.drain_events()
        self.server.start(self.settings, self.devices)
        deadline = time.monotonic() + 5
        while not self.server.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.is_running)
        self.assertTrue(self.client.connect())
        self.assert_ok(self.client.read_holding_registers(17, count=1, device_id=1))


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, settings=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        window = EmulatorMainWindow(settings or EmulatorSettings.default(), Path(directory.name) / "config.json")
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        return window

    def test_empty_start_and_save(self):
        window = self.make_window()
        self.assertEqual(window.device_list.count(), 0)
        self.assertEqual(window.register_model.rowCount(), 0)
        self.assertFalse(window.add_block_button.isEnabled())
        window._save_configuration()
        self.assertEqual(EmulatorSettings.load(window.config_path).devices, [])

    def test_add_device_range_creates_no_implicit_addresses(self):
        window = self.make_window()
        with patch("modbus_emulator.gui.get_text_input", return_value=("7-9", True)):
            window._add_devices()
        self.assertEqual(sorted(window.devices), [7, 8, 9])
        self.assertEqual(window.register_model.rowCount(), 0)
        self.assertTrue(window.add_block_button.isEnabled())

    def test_add_edit_remove_block_through_gui(self):
        window = self.make_window(EmulatorSettings.default(1))
        entry = block(start=55, count=2, name="Test")
        with patch("modbus_emulator.gui.BlockDialog") as factory:
            factory.return_value.exec.return_value = 1
            factory.return_value.result_block = entry
            window._add_block()
        self.assertEqual(window.register_model.rowCount(), 2)
        window.register_table.selectRow(0)
        with patch("modbus_emulator.gui.BlockDialog") as factory:
            factory.return_value.exec.return_value = 1
            factory.return_value.result_block = block("coils", 10, 5)
            window._edit_block()
        self.assertEqual(window.register_model.rowCount(), 5)
        window.register_table.selectRow(0)
        with patch("modbus_emulator.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            window._remove_block()
        self.assertEqual(window.register_model.rowCount(), 0)

    def test_area_filter_signed_values_and_read_only_operator_edits(self):
        settings = EmulatorSettings(devices=[DeviceSettings(1, blocks=[block(a.value) for a in DataArea])])
        window = self.make_window(settings)
        self.assertEqual(window.register_model.rowCount(), 12)
        window.area_filter.setCurrentIndex(window.area_filter.findData("input_registers"))
        self.assertEqual(window.register_model.rowCount(), 3)
        self.assertTrue(window.register_model.setData(window.register_model.index(0, 4), "-1"))
        self.assertEqual(window.devices[1].bank.read(DataArea.INPUT_REGISTERS, 0), [65535])

    def test_map_editing_is_disabled_while_server_runs(self):
        window = self.make_window(EmulatorSettings.default(1))
        window.server_expected_running = True
        window._set_configuration_enabled(False)
        self.assertFalse(window.add_block_button.isEnabled())
        self.assertFalse(window.copy_to_all_button.isEnabled())
        self.assertFalse(window.new_action.isEnabled())
        window.server_expected_running = False

    def test_block_dialog_builds_custom_range_and_preserves_values(self):
        dialog = BlockDialog()
        dialog.start_spin.setValue(65535)
        self.assertEqual(dialog.count_spin.maximum(), 1)
        dialog.value_edit.setText("0x1234")
        dialog.accept()
        self.assertEqual(dialog.result_block.values, [0x1234])
        edited = BlockDialog(block(values=[1, 2, 3]))
        edited.count_spin.setValue(4)
        edited.accept()
        self.assertEqual(edited.result_block.values, [1, 2, 3, 0])

    def test_copy_map_preserves_device_ids_and_independent_values(self):
        window = self.make_window(EmulatorSettings(devices=[DeviceSettings(1, blocks=[block(values=[1, 2, 3])]), DeviceSettings(2)]))
        with patch("modbus_emulator.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            window._copy_selected_to_all()
        self.assertEqual(window.devices[2].bank.read(DataArea.HOLDING_REGISTERS, 0, 3), [1, 2, 3])
        window.devices[1].bank.write(DataArea.HOLDING_REGISTERS, 0, [99])
        self.assertEqual(window.devices[2].bank.read(DataArea.HOLDING_REGISTERS, 0), [1])
        self.assertEqual(window.devices[2].unit_id, 2)

    def test_custom_serial_baudrate_survives_gui_round_trip(self):
        settings = EmulatorSettings.default()
        settings.serial.baudrate = 14400
        window = self.make_window(settings)
        self.assertEqual(window._collect_settings(validate=False).serial.baudrate, 14400)

    def test_opening_empty_configuration_discards_previous_map(self):
        window = self.make_window(EmulatorSettings(devices=[DeviceSettings(1, blocks=[block(values=[1, 2, 3])])]))
        empty_path = window.config_path.parent / "empty.json"
        EmulatorSettings.default().save(empty_path)
        with patch("modbus_emulator.gui.QFileDialog.getOpenFileName", return_value=(str(empty_path), "")):
            window._open_configuration()
        self.assertEqual(window.devices, {})
        self.assertIsNone(window.register_model.bank)
        self.assertEqual(window.register_model.rowCount(), 0)
        self.assertTrue(window.empty_map_label.isVisible())

    def test_invalid_startup_configuration_is_not_overwritten(self):
        from modbus_emulator.main import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_bytes(b'{"unexpected": 1}')
            with patch("sys.argv", ["run_emulator.py", "--config", str(path)]), \
                 patch("modbus_emulator.main.QApplication"), \
                 patch("modbus_emulator.main.QMessageBox.critical") as message:
                self.assertEqual(main(), 1)
                message.assert_called_once()
            self.assertEqual(path.read_bytes(), b'{"unexpected": 1}')

    def test_exe_configuration_uses_executable_directory(self):
        from modbus_emulator.main import default_config_path
        with patch("sys.frozen", True, create=True), patch("sys.executable", str(Path(tempfile.gettempdir()) / "emulator.exe")):
            self.assertEqual(default_config_path(), Path(tempfile.gettempdir()).resolve() / "emulator.json")


class ServerLifecycleTests(unittest.TestCase):
    def test_stop_during_startup_does_not_leave_server_running(self):
        settings = EmulatorSettings(tcp=TcpSettings(port=free_port()), devices=[DeviceSettings(1, blocks=[block()])])
        server = MultiDeviceModbusServer()
        self.addCleanup(server.stop)
        server.start(settings, [EmulatorDevice(1, "", RegisterBank(1, [block()]))])
        server.stop()
        self.assertFalse(server.is_active)
        self.assertFalse(server.is_running)

    def test_rtu_settings_and_custom_context_are_forwarded(self):
        captured = {}

        class FakeSerialServer:
            def __init__(self, context, **kwargs):
                captured.update(kwargs)
                captured["context"] = context
                self.serving = asyncio.get_running_loop().create_future()

            async def serve_forever(self, **kwargs):
                pass

            async def shutdown(self):
                if not self.serving.done():
                    self.serving.set_result(True)

        settings = EmulatorSettings(transport="rtu", devices=[DeviceSettings(7, blocks=[block()])])
        settings.serial.port = "test-port"
        server = MultiDeviceModbusServer()
        self.addCleanup(server.stop)
        with patch("modbus_emulator.server.ModbusSerialServer", FakeSerialServer):
            server.start(settings, [EmulatorDevice(7, "", RegisterBank(7, [block()]))])
            deadline = time.monotonic() + 5
            while not server.is_running and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.is_running)
            self.assertEqual(captured["port"], "test-port")
            self.assertEqual(captured["baudrate"], 19200)
            self.assertTrue(captured["allow_multiple_devices"])
            self.assertEqual(captured["context"].device_ids(), [7])
            server.stop()


if __name__ == "__main__":
    unittest.main()
