"""Serwer RTU/TCP z bankiem danych definiowanym przez użytkownika."""

from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime

from pymodbus.constants import ExcCodes
from pymodbus.datastore import ModbusServerContext
from pymodbus.exceptions import NoSuchIdException
from pymodbus.server import ModbusSerialServer, ModbusTcpServer

from .config import EmulatorSettings
from .register_bank import RegisterBank, RegisterBankError, RegisterValueError
from .register_map import FUNCTION_AREAS


@dataclass(slots=True)
class EmulatorEvent:
    kind: str
    message: str
    unit_id: int | None = None
    function_code: int | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class EmulatorDevice:
    unit_id: int
    name: str
    bank: RegisterBank


class RegisterServerContext(ModbusServerContext):
    """Adapter publicznego interfejsu datastore PyModbus 3.14.

    Własny bank obsługuje dokładne granice bitów i luki adresowe.
    Nie tworzymy drugiej kopii danych w simulatorze biblioteki.
    """

    def __init__(self, devices: list[EmulatorDevice], emit):
        # Pusta lista pozostawia ten kontekst jako datastore serwera PyModbus.
        self.simdevices = []
        self._banks = {device.unit_id: device.bank for device in devices}
        self._emit = emit

    def device_ids(self) -> list[int]:
        return list(self._banks)

    def _bank(self, device_id: int) -> RegisterBank:
        if device_id not in self._banks:
            raise NoSuchIdException(f"Brak Unit ID {device_id}")
        return self._banks[device_id]

    def _failure(self, error: RegisterBankError, device_id: int, func_code: int) -> ExcCodes:
        self._emit(EmulatorEvent("warning", str(error), device_id, func_code))
        return ExcCodes.ILLEGAL_VALUE if isinstance(error, RegisterValueError) else ExcCodes.ILLEGAL_ADDRESS

    async def async_getValues(self, device_id: int, func_code: int, address: int, count: int = 1):
        bank = self._bank(device_id)
        if (area := FUNCTION_AREAS.get(func_code)) is None:
            return ExcCodes.ILLEGAL_FUNCTION
        try:
            values = bank.read(area, address, count)
            return [bool(v) for v in values] if area.is_bit else values
        except RegisterBankError as error:
            return self._failure(error, device_id, func_code)

    async def async_setValues(self, device_id: int, func_code: int, address: int, values):
        bank = self._bank(device_id)
        if (area := FUNCTION_AREAS.get(func_code)) is None:
            return ExcCodes.ILLEGAL_FUNCTION
        try:
            bank.write(area, address, values)
            return None
        except RegisterBankError as error:
            return self._failure(error, device_id, func_code)


class MultiDeviceModbusServer:
    def __init__(self):
        self.events: queue.Queue[EmulatorEvent] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ModbusSerialServer | ModbusTcpServer | None = None
        self._running = threading.Event()
        self._stop_requested = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit(self, event: EmulatorEvent) -> None:
        self.events.put(event)

    def _trace_pdu(self, sending, pdu):
        if not sending:
            count = getattr(pdu, "count", 0)
            details = f"adres={getattr(pdu, 'address', 0)}, liczba={count}"
            if pdu.function_code == 23:
                details = (f"odczyt={pdu.read_address}, liczba={pdu.read_count}; "
                           f"zapis={pdu.write_address}, wartości={pdu.write_registers}")
            elif pdu.function_code == 22:
                details += f", AND=0x{pdu.and_mask:04X}, OR=0x{pdu.or_mask:04X}"
            elif pdu.function_code in {5, 6, 15, 16}:
                values = pdu.bits if pdu.function_code in {5, 15} else pdu.registers
                details += f", wartości={values}"
            self._emit(EmulatorEvent("request", f"ID {pdu.dev_id}: FC{pdu.function_code:02d}, {details}", pdu.dev_id, pdu.function_code))
        elif pdu.function_code & 0x80:
            self._emit(EmulatorEvent("warning", f"Odpowiedź wyjątkowa ID {pdu.dev_id}: FC{pdu.function_code & 0x7F:02d}, kod={pdu.exception_code}"))
        return pdu

    def start(self, settings: EmulatorSettings, devices: list[EmulatorDevice]) -> None:
        if self.is_active:
            raise RuntimeError("Serwer jest już uruchomiony")
        settings.validate()
        enabled_ids = {d.unit_id for d in settings.devices if d.enabled}
        enabled_devices = [d for d in devices if d.unit_id in enabled_ids]
        if {d.unit_id for d in enabled_devices} != enabled_ids:
            raise RuntimeError("Brak banku danych dla aktywnego urządzenia")
        self._stop_requested.clear()
        self._thread = threading.Thread(target=self._thread_main, args=(settings, enabled_devices), name="modbus-emulator-server", daemon=True)
        self._thread.start()

    def _thread_main(self, settings, devices) -> None:
        try:
            asyncio.run(self._serve(settings, devices))
        except Exception as error:
            self._emit(EmulatorEvent("error", str(error)))
        finally:
            self._running.clear()
            self._server = None
            self._loop = None
            self._emit(EmulatorEvent("stopped", "Serwer zatrzymany"))

    async def _serve(self, settings, devices) -> None:
        self._loop = asyncio.get_running_loop()
        context = RegisterServerContext(devices, self._emit)
        common = {"ignore_missing_devices": True, "trace_pdu": self._trace_pdu}
        if settings.transport == "rtu":
            serial = settings.serial
            self._server = ModbusSerialServer(context, port=serial.port, baudrate=serial.baudrate, bytesize=serial.bytesize,
                parity=serial.parity, stopbits=serial.stopbits, timeout=serial.timeout_seconds,
                handle_local_echo=serial.local_echo, allow_multiple_devices=True, **common)
            endpoint = f"{serial.port}, {serial.baudrate} {serial.bytesize}{serial.parity}{serial.stopbits}"
        else:
            self._server = ModbusTcpServer(context, address=(settings.tcp.host, settings.tcp.port), **common)
            endpoint = f"{settings.tcp.host}:{settings.tcp.port}"
        try:
            if self._stop_requested.is_set():
                return
            await self._server.serve_forever(background=True)
            if self._stop_requested.is_set():
                return
            self._running.set()
            ids = ", ".join(str(d.unit_id) for d in devices)
            self._emit(EmulatorEvent("started", f"Serwer {settings.transport.upper()} działa na {endpoint}; Unit ID: {ids}"))
            await self._server.serving
        finally:
            await self._server.shutdown()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_requested.set()
        loop, server = self._loop, self._server
        if loop is not None and server is not None and not loop.is_closed():
            coroutine = server.shutdown()
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except RuntimeError:
                coroutine.close()
            else:
                try:
                    future.result(timeout=timeout_seconds)
                except Exception as error:
                    self._emit(EmulatorEvent("error", f"Błąd zatrzymywania serwera: {error}"))
        if self.is_active:
            self._thread.join(timeout=timeout_seconds)

    def drain_events(self, limit: int = 500) -> list[EmulatorEvent]:
        events = []
        for _ in range(limit):
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events
