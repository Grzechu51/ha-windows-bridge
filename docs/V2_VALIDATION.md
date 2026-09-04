# Walidacja 2.0.0-alpha.1

Data: 2026-09-04. Windows 11 build 26200, Python 3.13.5, PySide6 6.11.2, PyInstaller 6.22.2.

| Sprawdzenie | Wynik |
| --- | --- |
| pytest, cały aktualny zestaw | 208 passed (1.89 s) |
| Układ 7 stron i 6 rodzajów nakładek, jasny/ciemny motyw | PASS |
| Dodatkowe przebiegi skalowania 125%, 150%, 200% | 8/8 testów w każdym przebiegu |
| Ruff | PASS |
| compileall | PASS |
| Bandit `-ll -ii` | 0 medium/high; jedna uwaga low B311 dla jittera reconnect (nie służy kryptografii) |
| pip-audit | Brak znanych podatności zależności; lokalny projekt 2.0.0a1 pominięty, bo nie jest pakietem z PyPI |
| PyInstaller | PASS, osobny folder dist/v2-alpha |
| Smoke-test końcowego EXE | Exit 0; okno, trzy wskaźniki i odczyt diagnostyki |
| Wersja EXE / manifest / kod / pyproject | 2.0.0-alpha.1 (metadane PEP 440: 2.0.0a1) |
| git diff --check | PASS |

Przejrzano zrzuty rzeczywistego renderowania Qt (offscreen), w tym stronę połączeń i poprawioną siatkę aplikacji. Testy HA wykorzystują API doubles — **nie oznacza to testu na rzeczywistym serwerze Home Assistant**. Testy DPI są testami logicznego skalowania Qt, nie pełnym testem DWM/HDR/RDP na kilku monitorach.

Prototyp miał 223 testy. Usunięto testy ściśle powiązane z wewnętrzną implementacją wycofanych managerów, dodano testy nowego runtime/protokołu/ACL/kolejki/placement/GUI. Liczby przed i po nie są bezpośrednią miarą pokrycia.

## Pakiet lokalny

- EXE: `dist/v2-alpha/HA Windows Bridge/HA Windows Bridge.exe`.
- Rozmiar całego folderu: 151 923 192 bajty (około 145 MiB).
- Pierwszy build z nieużywanymi bibliotekami GPU: 184 118 304 bajty. Ograniczenie pakowania: około 17,5% / 30,7 MiB.
- SHA256 EXE: `e8c0b4b57ede8d662f65f919422a9bf4ab695ee8b9a03394d60ee70222848da3`.
- Bez podpisu Authenticode, bez instalowania i bez publikowania w GitHub Releases.
- Adapter DXGI przeniesiono do `windows/capture.py`; nie jest importowany ani pakowany przez runtime alpha. To nie jest pomiar wykorzystania CPU podczas działania.

## Ograniczenia walidacji

Nie wykonano testu na produkcyjnym HA, wielogodzinnego burn-in, fizycznego sleep/resume, Snap Layouts, mixed-DPI/HDR/RDP ani odświeżenia HACS po publikacji. Pełna lista pozostałych prac znajduje się w `V2_REBUILD.md`.

To działająca baza nowej generacji, nie deklaracja zakończenia wszystkich bramek wydania 2.0.

## Diff

Statystyka zmian implementacji względem commita prototypu `31054e5` (bez tego pliku walidacji): patrz `V2_DIFF_STAT.txt`.
