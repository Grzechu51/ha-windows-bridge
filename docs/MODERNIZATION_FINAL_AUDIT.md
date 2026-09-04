# Modernizacja — raport końcowy etapu lokalnego

Stan: 2026-09-04, gałąź `codex/fluent-rebuild`, baza `320c1ec`.
To lokalna wersja rozwojowa, nie nowy release. Numer aplikacji nadal wynosi
`0.10.0-beta.5`; nie zastąpiono paczek opublikowanych na GitHubie.

## Wynik

Wdrożono partie dotyczące bezpieczeństwa, komunikacji, wykonawców zadań,
modelu i kolejki nakładek, podziału GUI, wspólnego motywu i MotionSystem oraz
cyklu życia integracji HA. Nie przepisywano projektu od zera, nie dodano
zależności runtime i nie kopiowano kodu repozytoriów referencyjnych.

Punkty wyjścia i uzasadnienia: [audyt](MODERNIZATION_AUDIT.md),
[architektura](MODERNIZATION_ARCHITECTURE.md). Referencje są źródłem konkretnych
decyzji, a nie deklaracją zgodności z całym WinUI lub HA Quality Scale.

## Co zmieniono

- Bezpieczeństwo: wspólna redakcja sekretów w logach i diagnostyce, również
  tokenów Bearer, wartości URL-encoded, wyjątków i zagnieżdżonych danych.
  Raport czyta ograniczony ogon dużego logu.
- WebSocket: sprzątanie po nieudanym handshake, zamykanie socketu przy stop,
  ping/pong z limitem oczekiwania, reconnect z backoff i jitter.
- MQTT: ograniczona kolejka szeregowa komend odciąża wątek sieciowy. Retained
  commands nadal są odrzucane; zatrzymanie anuluje oczekujące zadania.
- Sensory: niezależne harmonogramy odczytu, ostatnia poprawna wartość i
  ograniczenie powtarzanych błędów. Awaria jednego odczytu nie pomija reszty.
- Media: zamykanie pętli asyncio przez jej właściciela, anulowanie zadań,
  ochrona przed równoczesnym tworzeniem i restartem aktywnego runnera.
- Konfiguracja: walidacja kontenerów i wartości niefinitywnych w nakładkach.
  Dodano opcjonalne `reduced_motion`; istniejące identyfikatory i pola zachowano.
- Nakładki: osobne model, kolejka priorytetowa, pozycjonowanie i rysowanie karty.
  Przepełnienie kolejki nie wyrzuca już najważniejszej wiadomości.
  Animacja wejścia/wyjścia nie zmienia rozmiaru siatki tekstu w każdej klatce.
- Monitory: unieważnianie cache przechwytywania po zmianie topologii/DPI,
  niedublowane subskrypcje QScreen i jawne odłączanie uchwytów sygnałów.
- GUI: osobne moduły stron, wspólna paleta dark/light, czytelniejsze stany kontrolek,
  responsywna nawigacja oraz zakładki MQTT / Home Assistant. Minimum 800 × 600 DIP.
  Status pozostaje widoczny także po zwinięciu nawigacji.
- MotionSystem: wejście 220 ms, wyjście 160 ms, przejście strony/przesunięcie
  180 ms, przełącznik 120 ms. Obsługa ograniczenia animacji i przerywania przejść.
  Tokeny hover/press są przygotowane; stany tych kontrolek nie są wszędzie animowane.
- Tray: skróty do ustawień oraz pokazania i zamknięcia przykładowej nakładki.
  Pozostawiono wcześniejszą akcję ponownego połączenia.
- HA: diagnostyka oparta na dozwolonych polach, reconfigure nazwy połączenia
  bezpośredniego bez zmiany ID, publiczny parametr `last_step` i cleanup
  subskrypcji przez `async_on_remove`.

## Status ustaleń audytu

| Ustalenia | Status w tym etapie |
| --- | --- |
| H1–H6 | Poprawki wdrożone i testowane. Zachowanie po rzeczywistej utracie sieci / sleep wymaga próby sprzętowej. |
| M1–M2 | Częściowo: oddzielono strony, motyw, motion i czystą logikę nakładek. MainWindow i OverlayManager nadal zawierają koordynację wielu funkcji; nie rozbijano ich sztucznie na puste kontrolery. |
| M3–M4, M6–M7, M12 | Wdrożone; testy logiki, układu i reduced motion. |
| M5 | Częściowo: szeregowe komendy audio, cleanup timerów i loggera. Jednorazowe skany/testy połączeń nadal mają dotychczasowe wątki. |
| M8 | Responsywność poprawiona. Nowy adapter Snap Layouts / natywnego hit-testu nie został wdrożony. |
| M9–M10 | Wdrożone; testy z atrapami publicznych API. Rzeczywisty reload/unload HA i hassfest pozostają przed wydaniem. |
| M11 | Jawnie pozostawione: direct nie potwierdza odbioru przez PC. Nie dodano ACK ani deduplikacji zmieniającej protokół. |
| M13 | Reset capture i cleanup sygnałów wdrożone; hotplug i mieszane DPI wymagają testu na monitorach. |
| L1–L3 | Wdrożone. |
| L4 | Testy tworzą pełne okno Qt i przerywają animacje. Smoke gotowego EXE sprawdza importy/natywne zależności, nie cały interaktywny workflow. |

## Weryfikacja

Windows 11, Python 3.13.5; testy GUI używają backendu Qt offscreen.

| Kontrola | Wynik |
| --- | --- |
| Bazowy pytest przed zmianami | 177 passed, 10,87 s |
| Pełny pytest po zmianach | 223 passed, 11,38 s |
| GUI, osobny przebieg | 48 passed, 10,59 s |
| Logika HA i transport MQTT, osobny przebieg | 35 passed, 0,44 s |
| Układ / nakładki 125% DPI | 11 passed, 3,08 s |
| Układ / nakładki 150% DPI | 11 passed, 3,68 s |
| Układ / nakładki 200% DPI | 11 passed, 5,17 s |
| Ruff | Bez błędów |
| compileall | Bez błędów |
| Bandit | Brak zgłoszeń; 14 istniejących, jawnych wyłączeń reguł |
| pip-audit | Brak znanych podatności sprawdzonych zależności; lokalny projekt nie jest audytowany przez bazę PyPI |
| PyInstaller 6.22.2 | Paczka zbudowana |
| Gotowy EXE --smoke-test | Kod wyjścia 0 |
| git diff --check | Bez błędów whitespace; ostrzeżenia o normalizacji LF/CRLF |

Podane czasy testów nie są benchmarkiem działania aplikacji.
Obejrzano wyrenderowane ekrany, w tym formularz bezpośredniego połączenia oraz
jasne ustawienia. Artefakty: `build/modernization-layouts-final` i
`build/modernization-dpi`.

Nie uruchomiono pełnego mypy/pyright. Ruff i compileall nie zastępują sprawdzania
typów. Testy HA z atrapami sprawdzają lokalny kontrakt, nie certyfikują zgodności
ze wszystkimi wersjami Home Assistant.

## Jak uruchomić lokalnie

1. Zamknij dotychczasowy HA Windows Bridge z zasobnika: **Zakończ**.
2. Przed testem zachowaj eksport ustawień. Jeśli potrzebujesz pełnego powrotu,
   zrób prywatną kopię katalogu `%LOCALAPPDATA%\HAWindowsBridge`; zawiera także
   zaszyfrowane dane dostępowe, więc nie wysyłaj go do GitHuba.
3. Uruchom w PowerShell:

```powershell
cd "F:\Codex\HA MQTT PC"
& ".\dist\modernization-preview\HA Windows Bridge\HA Windows Bridge.exe"
```

Zachowaj cały katalog paczki, w tym `_internal`; sam plik EXE nie wystarczy.
Paczka używa dotychczasowych ustawień i może automatycznie łączyć się zgodnie
z ich konfiguracją. Testuj przykłady w **Funkcje → Nakładka** lub przez tray.
Nie przywrócono usuniętego konfiguratora popupów.

Ponowne testy kodu bez przebudowy:

```powershell
.\scripts\test_local.ps1 -SkipBuild
```

## Przed publikacją

- Rzeczywisty pomiar CPU/GPU/RAM: idle, pojedyncza nakładka i kilka kart,
  Acrylic / Liquid Glass, statyczny i zmienny pulpit.
- Windows 10/11, 60/120/144 Hz, monitory o różnym DPI, hotplug, lock/unlock,
  sleep/hibernate, restart Explorer.
- Restart HA i brokera, utrata sieci i powrót, dostępność encji, komendy mediów,
  reconfigure/unload/reload w rzeczywistym HA.
- CI integracji (hassfest/HACS), instalator i aktualizacja z dotychczasowego wydania.
- Osobna decyzja o Snap/Mica, ACK/availability oraz dalszym podziale controllerów.

Nie potwierdzono poprawy liczbowej CPU ani płynności 144 fps. Nie dodano nowego
Mica do głównego okna; zachowano istniejące adaptery Acrylic/GPU i ich fallback.
Nie potwierdzono wyświetlania ikony w interfejsie HACS samą obecnością plików PNG.
Gałąź, build i dokumentacja są lokalne; nie wykonano push, taga ani release.

