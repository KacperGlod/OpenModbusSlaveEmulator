# Open Modbus Slave Emulator

A desktop application for emulating multiple Modbus RTU/TCP slave devices.
Define your own devices, address ranges, and values without a predefined register map.
New configurations start empty. The current user interface is in Polish.

## Getting started

Requires Python 3.10 or later. Run these commands from the project directory
in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_emulator.py
```

On Linux, use `.venv/bin/python` instead of `.venv\Scripts\python.exe`.

Optional command-line arguments:

- `--devices 10` creates 10 devices with empty maps when the configuration file
  does not yet exist. Supported counts: 0–247.
- `--config path.json` selects a configuration file.

## Setting up an emulator

1. Add a device or a range of Unit IDs, such as `1-10`. Supported IDs: 1–247.
2. Select a device and add an address range.
3. Choose the data area, starting PDU address, address count, and an optional name.
4. Set values in the table and configure the TCP or RTU connection.
5. Start the server. Values remain editable while it is running.

Select a table row to edit or remove the range containing that address.
You can also copy the selected device's map and values to all other devices;
this replaces their existing ranges and values.
Stop the server before changing address maps or enabling and disabling devices.

## Data areas and addressing

| JSON area | Function codes | Modbus client access |
| --- | --- | --- |
| `coils` | FC01, FC05, FC15 | Read/write, 0 or 1 |
| `discrete_inputs` | FC02 | Read-only, 0 or 1 |
| `holding_registers` | FC03, FC06, FC16, FC22, FC23 | Read/write, 16-bit |
| `input_registers` | FC04 | Read-only, 16-bit |

Addresses are raw PDU addresses in the range **0–65535**. Address 0 in the
configuration is address 0 in a request. Convert conventional register numbers
such as 40001 to the appropriate data area and PDU address in your client.
Each device and data area has an independent address map.

Only explicitly defined addresses are accessible. Requests that include gaps
or undefined addresses return an Illegal Data Address exception. Ranges within
the same device and data area cannot overlap; adjacent ranges can be read together.

Coils and holding registers can be marked read-only (RO) for Modbus clients.
The GUI operator can still edit these values, as well as discrete inputs and
input registers.

Registers store values from 0 to 65535. The editor accepts decimal, hexadecimal
(`0x1234`), and signed 16-bit values (-32768 to 32767, stored in two's complement).
The Signed 16 column shows the signed interpretation. To represent 32-bit values,
floating-point numbers, or strings, encode them across consecutive registers in
your client. The emulator stores raw 16-bit words without automatic conversion.

## Connections and logging

TCP listens on `127.0.0.1:1502` by default. All devices share one TCP endpoint
or, in RTU mode, one serial port.

The RTU interface offers 1200, 2400, 4800, 9600, 19200, and 38400 baud.
Custom baud rates from 1 to 38400 can be set in JSON and are preserved by the GUI.
A connected pair of virtual serial ports can be used to communicate between
two applications on the same computer.

Disabled devices and unknown Unit IDs do not respond. Broadcast is disabled.
The log displays requests, rejected operations, and server status. The request
counter includes invalid requests, and the log view keeps the latest 2000 lines.

## Configuration files

Use the file menu to create, open, save, or save a copy of a JSON configuration.
Values are also saved when closing the application.

The default file is `emulator.json`, stored in the project directory when running
from source or next to the executable when using the Windows build.
This local file is excluded from Git.

Configuration files use `"format": "modbus-slave-emulator"` and `"version": 1`.
Unsupported formats and unknown fields are rejected. An invalid configuration
at startup displays an error and exits without overwriting the file.

To open the example covering all four data areas:

```powershell
.\.venv\Scripts\python.exe run_emulator.py --config emulator.example.json
```

Use Save As before making changes to keep the example unchanged; otherwise,
changes will be saved back to the example file.

Each device contains a `blocks` list. Each block defines `area`, `start`, and
`count`, with optional `name`, `read_only`, and `values` fields.
Omitted or empty `values` initialize the range to zero. A nonempty list must
contain exactly `count` values.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover configuration validation, GUI behavior, TCP reads and writes for all
data areas, isolation between 50 devices, address boundaries, read-only ranges,
and gaps in address maps. RTU requires separate testing with a physical serial
port or a connected pair of virtual ports.

## Building a Windows executable

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm OpenModbusSlaveEmulator.spec
```

The executable is created at `dist/OpenModbusSlaveEmulator.exe` and runs without
a separate Python installation. User configuration files are not bundled.
