# Zasady pracy nad Open Modbus Slave Emulator

Nazwa repozytorium: `OpenModbusSlaveEmulator`.

Instrukcje dotyczą całego repozytorium. Celem jest czytelny, uniwersalny emulator
Modbus RTU/TCP, który łatwo rozwijać i którego obsługa jest zrozumiała.

## Założenia produktu

- Nowa konfiguracja jest pusta. Urządzenia i zakresy danych definiuje użytkownik.
- Nie dodawaj zaszytych map, nazw ani wartości charakterystycznych dla konkretnej
  aplikacji lub urządzenia. Przykłady mają być neutralne, opcjonalne i oddzielone
  od konfiguracji uruchomieniowej.
- Zachowuj niezależność urządzeń i czterech obszarów Modbus. Adresy są surowymi
  adresami PDU 0..65535; niezdefiniowane adresy pozostają niedostępne.
- Rozróżniaj uprawnienia klienta Modbus i operatora GUI. Operator może ustawiać
  dane wejściowe i RO. Waliduj cały zapis przed zmianą wartości.
- Wczytanie nieprawidłowej konfiguracji nie może nadpisywać pliku ani po cichu
  zmieniać jego znaczenia. Zmiany formatu wymagają jawnego wersjonowania.

## Czysty kod i moduły

- Wybieraj najprostsze rozwiązanie spełniające wymagania. Używaj opisowych nazw,
  krótkich funkcji i jawnych zależności; unikaj ukrytych efektów ubocznych.
- Oddzielaj model danych, walidację konfiguracji, komunikację Modbus i GUI.
  Logika danych powinna działać bez Qt i transportu, a GUI korzystać z jej API.
- Twórz moduł, gdy wydzielasz spójną odpowiedzialność. Nie dopisuj całej logiki
  do `gui.py`, ale też nie buduj dodatkowych warstw bez konkretnej potrzeby.
- Obecny podział: `config.py` — konfiguracja; `register_map.py` — typy obszarów;
  `register_bank.py` — dane; `server.py` — protokół i transport;
  `models.py`, `dialogs.py`, `gui.py` — prezentacja i obsługa użytkownika.
  Rozwijaj ten podział zgodnie z odpowiedzialnościami, nie limitem długości pliku.
- Utrzymuj jedno źródło prawdy dla wartości i reguł walidacji. Usuwaj duplikację
  oraz kod, który przestał być używany po zmianie.
- Komentarze mają wyjaśniać powód lub ograniczenie, a nie powtarzać kod.
  Nie zostawiaj zakomentowanych implementacji, debugowych wydruków ani atrap.
- Dodawaj zależności tylko wtedy, gdy rozwiązują rzeczywistą potrzebę.
  Zachowuj zgodność z wersją Pythona opisaną w README.

## Zrozumiała aplikacja

- Stosuj spójne polskie komunikaty i nazewnictwo; standardowe terminy Modbus
  mogą pozostać w oryginale. Pusty widok powinien wskazywać następny krok.
- Komunikat błędu ma wyjaśniać problem i sposób poprawy. Szczegóły techniczne
  pokazuj wtedy, gdy pomagają użytkownikowi podjąć decyzję.
- Waliduj dane przy wprowadzaniu i w warstwie modelu. Jasno pokazuj stan serwera
  oraz dostępność operacji, w tym konieczność zatrzymania go przed zmianą mapy.
- Komunikacja i operacje blokujące nie mogą zamrażać GUI. Współdzielone dane
  aktualizuj bezpiecznie między wątkami, z przewidywalnym startem i zatrzymaniem.

## Porządek w repozytorium

- Ograniczaj zmiany do zadania. Unikaj przy okazji masowego formatowania,
  przemianowywania i refaktoryzacji niezwiązanych z celem.
- Nie wersjonuj `.venv/`, `build/`, `dist/`, cache, logów, lokalnej konfiguracji,
  sekretów ani plików tymczasowych. Utrzymuj adekwatny `.gitignore`.
- Nie dodawaj kopii zapasowych plików, jednorazowych skryptów ani zbędnych
  dokumentów. Trwałe narzędzia i dokumentacja muszą mieć jasne zastosowanie.
- Pakiet aplikacji ma zawierać wyłącznie potrzebny kod i zależności. Nie dołączaj
  lokalnych danych użytkownika ani bibliotek przypadkowo znalezionych w systemie.
- Aktualizuj README, gdy zmienia się obsługa, konfiguracja, instalacja lub build.
  Szanuj istniejące zmiany użytkownika i pozostałe projekty poza tym repozytorium.

## Weryfikacja

- Testuj zachowanie, a nie kopię implementacji. Przy zmianach logiki uwzględniaj
  istotne granice, błędne dane, izolację urządzeń i ograniczenia zapisu.
- Uruchamiaj testy odpowiednie do zmiany. Dla samej dokumentacji wystarczy
  sprawdzenie treści i diffu; nie przebudowuj EXE bez powodu.
- Zmiany GUI sprawdzaj również pod kątem czytelności i układu. Zmiany pakowania
  wymagają zbudowania i uruchomienia gotowego EXE.
- Raportuj faktycznie wykonane sprawdzenia i ich ograniczenia. Test TCP ani mock
  transportu nie jest potwierdzeniem działania na fizycznym porcie RTU.

Polecenia PowerShell z katalogu repozytorium:

```powershell
.\.venv\Scripts\python.exe run_emulator.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm OpenModbusSlaveEmulator.spec
```

## Komunikacja i commity — obowiązkowo

- Komunikuj się z użytkownikiem po polsku. Podsumowuj rezultat, weryfikację
  i istotne ograniczenia w sposób krótki i konkretny.
- Po każdym zadaniu zmieniającym repozytorium **zawsze podaj na czacie propozycję
  nazwy commita**, również gdy użytkownik nie poprosi o nią ponownie.
- Nazwa powinna być krótka, po angielsku i opisywać konkretną zmianę. Stosuj
  spójną konwencję z historią repozytorium. Przykład: `Add editable data ranges`.
- Przy kilku niezależnych zmianach zaproponuj sensowny podział i nazwy commitów.
  Gdy nie ma zmian do zapisania, powiedz to wprost; nie proponuj pustego commita.
- Odróżniaj propozycję nazwy od faktycznego utworzenia commita. Wykonuj operacje
  Git w zakresie zleconym przez użytkownika i jasno informuj o ich wyniku.
