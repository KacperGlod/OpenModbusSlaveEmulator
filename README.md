# Open Modbus Slave Emulator

Nazwa repozytorium: `OpenModbusSlaveEmulator`.

Uniwersalny emulator wielu urządzeń Modbus RTU/TCP z interfejsem PyQt6.
Mapa danych powstaje w konfiguracji użytkownika. Nowa konfiguracja jest pusta.

## Uruchomienie

Wymagany Python 3.10 lub nowszy. Polecenia Windows PowerShell, z katalogu
projektu `OpenModbusSlaveEmulator`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_emulator.py
```

Na Linux użyj `.venv/bin/python` zamiast `.venv\Scripts\python.exe`.
Opcja `--devices 10` tworzy 10 pustych urządzeń przy pierwszym uruchomieniu.
Opcja `--config ścieżka.json` wybiera osobny plik konfiguracji.

## Pierwsza konfiguracja

1. Dodaj urządzenie lub zakres Unit ID, np. `1-10` (obsługiwane ID: 1–247).
2. Wybierz urządzenie i kliknij **Dodaj zakres**.
3. Wybierz obszar, adres początkowy PDU, liczbę adresów i opcjonalną nazwę.
4. Dodaj kolejne zakresy, ustaw wartości w tabeli i wybierz parametry TCP lub RTU.
5. Kliknij **Uruchom serwer**. Wartości można zmieniać podczas pracy.

Zaznacz wiersz w tabeli, aby edytować lub usunąć cały zakres zawierający ten adres.
Kopiowanie mapy i wartości do wszystkich urządzeń zastępuje ich zakresy.
Zmiana mapy i dostępności urządzeń wymaga zatrzymania serwera.

## Obszary i adresowanie

| Obszar JSON | Funkcje | Dostęp klienta |
| --- | --- | --- |
| `coils` | FC01, FC05, FC15 | odczyt/zapis 0 lub 1 |
| `discrete_inputs` | FC02 | odczyt 0 lub 1 |
| `holding_registers` | FC03, FC06, FC16, FC22, FC23 | odczyt/zapis 16 bit |
| `input_registers` | FC04 | odczyt 16 bit |

Adresy są surowymi adresami PDU **0..65535**. Adres 0 w konfiguracji oznacza
adres 0 w żądaniu. Konwencjonalne numery typu 40001 należy przeliczyć po stronie
klienta na właściwy obszar i adres PDU. Ten sam adres może występować niezależnie
w każdym obszarze oraz w każdym urządzeniu.

Istnieją wyłącznie adresy dodane przez użytkownika. Luki i żądania wychodzące
poza zdefiniowany zakres zwracają wyjątek Illegal Data Address. Zakresy w tym
samym obszarze nie mogą się nakładać; sąsiednie można odczytywać wspólnie.

Zakres coils lub holding registers można dodatkowo oznaczyć jako RO.
Operator w GUI może edytować również dane RO oraz obszary wejściowe.
Rejestry przechowują wartości 0..65535; edytor przyjmuje decimal, `0xHEX`
i liczby signed 16 (-32768..32767, zapisywane jako uzupełnienie do dwóch).
Kolumna Signed 16 pokazuje interpretację tej samej wartości. Obsługiwane są
surowe słowa 16 bit; wartości 32 bit, float i napisy można kodować w kolejnych
rejestrach po stronie klienta. Emulator nie wykonuje automatycznych przeliczeń.

## Transport

TCP domyślnie nasłuchuje na `127.0.0.1:1502`. Wszystkie urządzenia współdzielą
jeden endpoint. W RTU współdzielą jeden port szeregowy; dostępne prędkości GUI:
1200, 2400, 4800, 9600, 19200 i 38400 baud. Konfiguracja JSON może wskazać
inną prędkość z zakresu 1..38400, zachowywaną przez GUI.
Do połączenia dwóch aplikacji na jednym komputerze
można użyć pary połączonych wirtualnych portów szeregowych.
Urządzenia wyłączone i nieznane Unit ID nie odpowiadają. Broadcast jest wyłączony.

Log pokazuje żądania, odrzucone operacje i stan serwera. Licznik zlicza każde
odebrane żądanie, również niepoprawne. Widok logu zachowuje ostatnie 2000 wierszy.

## Pliki konfiguracji

Menu **Plik** umożliwia utworzenie nowej konfiguracji oraz otwieranie i zapis JSON.
Wartości są zapisywane również przy zamknięciu okna. Domyślny lokalny
`emulator.json` jest ignorowany przez Git. Dla EXE znajduje się obok pliku
wykonywalnego; dla uruchomienia ze źródeł — w katalogu projektu.

Plik ma identyfikator `"format": "modbus-slave-emulator"` oraz `"version": 1`.
Identyfikator formatu pozostaje stały, aby zachować zgodność istniejących plików.
Inne formaty i nieznane pola są odrzucane. Błąd otwarcia konfiguracji przy starcie
kończy aplikację z komunikatem, bez nadpisywania pliku.
Neutralny przykład czterech obszarów można otworzyć przez:

```powershell
.\.venv\Scripts\python.exe run_emulator.py --config emulator.example.json
```

W takim przypadku zmiany zostaną zapisane do pliku przykładu; do własnej pracy
użyj **Zapisz jako**. Każde urządzenie zawiera listę `blocks`. Zakres zawiera
`area`, `start`, `count`, opcjonalne `name`, `read_only` i `values`.
Pominięte lub puste `values` oznacza zera; podana lista musi mieć długość `count`.

## Testy i EXE

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm OpenModbusSlaveEmulator.spec
```

Testy obejmują walidację, GUI, odczyty i zapisy wszystkich obszarów przez TCP,
niezależność 50 urządzeń, granice adresów, RO i luki w mapie.
RTU wymaga osobnego sprawdzenia z portem fizycznym lub wirtualną parą portów.
Gotowy plik powstaje w `dist/OpenModbusSlaveEmulator.exe`.
Pakiet nie dołącza plików konfiguracji ani dodatkowych zasobów aplikacyjnych.
Specyfikacja budowania na Windows ogranicza wyszukiwanie bibliotek DLL do Qt,
Pythona i Windows, aby biblioteki innych aplikacji w PATH nie trafiły do paczki.
