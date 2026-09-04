<p align="center">
  <img src="https://raw.githubusercontent.com/Grzechu51/ha-windows-bridge/main/assets/icon.png" alt="HA Windows Bridge" width="128">
</p>

<h1 align="center">HA Windows Bridge</h1>

> Ta gałąź zawiera **2.0.0-alpha.4**: nowy rdzeń, GUI i protokół integracji.
> Wersja przedpremierowa do testów: [pobierz 2.0 alpha](https://github.com/Grzechu51/ha-windows-bridge/releases/tag/v2.0.0-alpha.4).
> Zacznij od [instrukcji 2.0](docs/V2_QUICKSTART.md) i [raportu przebudowy](docs/V2_REBUILD.md).
> Instrukcje instalacji opublikowanych wydań poniżej dotyczą wcześniejszej linii 0.x.

<p align="center">Sterowanie komputerem z Windows w Home Assistant przez lokalne MQTT.</p>

HA Windows Bridge łączy aplikację Windows z integracją Home Assistant. Pokazuje tylko
funkcje włączone w aplikacji, dzięki czemu urządzenie w HA pozostaje czytelne.

## Możliwości

- głośność i wyciszenie Windows oraz osobny Media Player dla każdego wybranego programu;
- aktywne multimedia z okładką, czasem i sterowaniem;
- aktywna aplikacja, okno, bezczynność i blokada Windows;
- osobna telemetria CPU, RAM i GPU;
- Windows Update, wymagany restart, czas działania, zasilanie i bateria;
- wybrane dyski i urządzenia Windows;
- powiadomienia i nowoczesna nakładka ekranowa;
- opcjonalna blokada, uśpienie, restart i wyłączenie komputera.

Wszystkie funkcje dodatkowe są domyślnie wyłączone.

## Wymagania

- Windows 10 lub 11 x64;
- Home Assistant z działającą integracją MQTT i brokerem;
- HACS do zalecanej instalacji integracji.

Nie wystawiaj niezabezpieczonego brokera MQTT do Internetu. Poza siecią lokalną użyj
VPN albo poprawnie skonfigurowanego TLS.

## Instalacja

### 1. Integracja Home Assistant

[![Otwórz repozytorium w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

1. W HACS otwórz **⋮ → Custom repositories**.
2. Dodaj `https://github.com/Grzechu51/ha-windows-bridge` jako **Integration**.
3. Pobierz **HA Windows Bridge** i uruchom Home Assistant ponownie.

Przy instalacji ręcznej skopiuj `custom_components/ha_windows_bridge` do
`config/custom_components/ha_windows_bridge` i uruchom HA ponownie.

### 2. Aplikacja Windows

1. Otwórz [najnowsze wydanie](https://github.com/Grzechu51/ha-windows-bridge/releases/latest).
2. Pobierz `HA-Windows-Bridge-Setup-0.9.0.exe`.
3. Opcjonalnie porównaj SHA-256 z `SHA256SUMS-0.9.0.txt`.
4. Uruchom instalator.

`HA-Windows-Bridge-0.9.0-win64.zip` to wersja przenośna. Po rozpakowaniu zachowaj cały
katalog wraz z folderem `_internal`.

### Wersja testowa 0.10.0-beta.5

W HACS włącz dla tego repozytorium obsługę wersji **pre-release/beta**, a następnie
wybierz **Redownload → Need a different version? → v0.10.0-beta.5**. Aplikację Windows
pobierz z wydania oznaczonego **Pre-release** na GitHubie. Stabilne `v0.9.0` pozostaje
wydaniem domyślnym.

## Pierwsze uruchomienie

1. Podaj adres, port, użytkownika i hasło MQTT.
2. Kliknij **Testuj połączenie**.
3. W **Aplikacje** wybierz programy, którymi chcesz sterować.
4. W **Funkcje** włącz potrzebne encje.
5. Kliknij **Zapisz i zastosuj**.
6. Potwierdź wykryty komputer w **Ustawienia → Urządzenia i usługi** Home Assistant.

Hasło MQTT jest zapisane przez Windows DPAPI i nie trafia do eksportu konfiguracji ani
raportu diagnostycznego.

## Funkcje aplikacji

- **System i dyski** — stan Windows, osobne moduły CPU, RAM i GPU oraz wybrane woluminy.
- **Audio** — osobne odtwarzacze aplikacji, Media Player aktywnej sesji Windows, balans
  kanałów i liczba sesji.
- **Urządzenia** — wybór aktywnych lub nieaktywnych urządzeń widocznych w Windows.
- **Nakładka** — wiadomości, statusy, obrazy i multimedia na pulpicie. W aplikacji
  wybierasz monitor i sprawdzasz przykłady, a treść i wygląd ustawiasz w akcji Home Assistant.

Wyłączenie modułu usuwa jego encje po zapisaniu i ponownym opublikowaniu konfiguracji.

## Media Player

Każda aplikacja włączona na liście sterowania głośnością automatycznie otrzymuje własną
encję `media_player`. Pozwala ona zmieniać głośność, włączać lub wyłączać wyciszenie
oraz rozpoznać, czy program jest uruchomiony. Dotychczasowe osobne encje głośności,
wyciszenia i stanu pozostają dostępne dla istniejących dashboardów oraz automatyzacji.

Włącz **Media Player** w aplikacji, aby dodać do Home Assistant aktywną sesję
multimediów Windows. Dostępne informacje i przyciski zależą od programu odtwarzającego.

## Nakładka Windows

1. W aplikacji otwórz **Funkcje → Nakładka**, włącz wiadomości na ekranie i wybierz monitor.
2. W sekcji **Przykłady nakładek** sprawdź wybrany układ przyciskiem **Pokaż przykład**.
3. W automatyzacji Home Assistant dodaj akcję **HA Windows Bridge: Wyświetl nakładkę**
   (`ha_windows_bridge.show_overlay`) i jako cel wybierz encję nakładki komputera.
4. Wypełnij treść albo rozwiń **Encje i obrazy**, aby wybrać encję tytułu, wiadomości,
   kamerę, obraz lub jego adres. Odtwarzacz wybierzesz w sekcji **Treść**.

Przykład statusu baterii:

```yaml
action: ha_windows_bridge.show_overlay
target:
  entity_id: notify.pc_windows_overlay
data:
  title: Bateria
  message_entity: sensor.laptop_battery
  progress_entity: sensor.laptop_battery
  icon: mdi:battery
  layout: status
```

Treść i wygląd zapisujesz razem z automatyzacją w Home Assistant. Nie ma osobnego
katalogu szablonów w aplikacji Windows. Wybrana encja dostarcza bieżący stan przy
wywołaniu akcji; do kolejnych zmian użyj `update_overlay` z tym samym `notification_id`.

Po włączeniu nakładki użyj akcji `ha_windows_bridge.show_overlay`. Najprostsza komenda
wyświetlająca aktualne multimedia z prawdziwym czasem i postępem utworu:

```yaml
action: ha_windows_bridge.show_overlay
target:
  entity_id: notify.pc_windows_overlay
data:
  notification_id: now_playing
  media: true
  pinned: true
  show_close_button: true
  size_mode: auto
  background_effect: liquid
  edge_offset: 16
```

`pinned` wyłącza automatyczne zamknięcie. `show_close_button` pokazuje **×**, a
`close_on_click` pozwala zamknąć kartę kliknięciem. Każda z tych opcji jest niezależna.

Tryb `auto` dopasowuje kartę do treści i ignoruje ręczne wymiary. Po wybraniu trybu
ręcznego podaj rozmiar:

```yaml
size_mode: manual
width: 520
height: 220
```

Pole **Efekt tła** pozwala wybrać jednolitą powierzchnię, standardowe rozmycie
**Acrylic** albo **Liquid Glass**. Pole **Odstęp od krawędzi** odsuwa kartę w głąb
ekranu. Ikonę wybiera się z biblioteki MDI Home Assistant.

Tryb automatyczny dobiera układ kompaktowy, standardowy, multimedialny albo kamerę.
Priorytet decyduje o kolejności wyświetlania. `show_lifetime` włącza pasek pozostałego
czasu, a `pause_on_hover` zatrzymuje automatyczne zamknięcie po najechaniu.

Do krótkich wskaźników, takich jak bateria, CPU i RAM, wybierz układ **Status** oraz
sposób wyświetlania **Obok siebie**. Maksymalnie cztery karty z różnymi
`notification_id` pozostają widoczne równocześnie; gdy brakuje miejsca, układ przechodzi
do kolejnego rzędu. Każdą wartość można później aktualizować po jej ID:

```yaml
action: ha_windows_bridge.show_overlay
target:
  entity_id: notify.pc_windows_overlay
data:
  notification_id: laptop_battery
  title: Bateria
  message: "{{ states('sensor.laptop_battery') }}%"
  icon: mdi:battery
  progress_entity: sensor.laptop_battery
  layout: status
  display_mode: parallel
  duration: 12
```

Jeszcze mniejszy układ **Znacznik** tworzy kapsułkę podobną do wskaźników telewizora:
może zawierać ikonę MDI, miniaturę z pola `image`, krótką wartość albo samą ikonę.
Połącz kilka znaczników przez `display_mode: parallel`, aby zbudować pasek baterii,
świateł, obecności i czasu. Wartość może pochodzić z `message`; jeśli pozostanie pusta,
używany jest procent `progress`, a następnie `title`.

Zamiast sesji z komputera możesz wskazać dowolną encję `media_player` dostępną w Home
Assistant. Nakładka pobierze jej tytuł, wykonawcę, postęp i okładkę:

```yaml
media_player_entity: media_player.salon
```

W układzie multimediów okładka jest eksponowana po prawej stronie. Lewa część, tekst
i pasek postępu otrzymują dopasowaną jasną lub ciemną paletę z zachowaniem kontrastu.

Postęp i czas mogą być stałą wartością, stanem encji albo atrybutem. Możesz też użyć
szablonu Home Assistant, na przykład:

```yaml
progress: "{{ (states('sensor.postep') | float * 100) | round }}"
```

Istniejącą wiadomość z `notification_id` zmienisz akcją `update_overlay`, usuniesz
przez `remove_overlay`, a całą kolejkę wyczyścisz przez `clear_overlay`.

## Testowanie lokalne przed publikacją

Zmiany można sprawdzać bez publikowania na GitHubie. W zakładce **Funkcje → Nakładka**
włącz wiadomości ekranowe, wybierz przykład i kliknij **Pokaż przykład**. Dostępne są
wiadomości, statusy, małe wskaźniki, kamera, Media Player oraz oba efekty rozmycia.
Przykłady używają danych demonstracyjnych i nie wymagają połączenia z Home Assistant.

Uruchomienie z kodu źródłowego:

```powershell
cd "F:\Codex\HA MQTT PC"
.\.venv\Scripts\python.exe main.py
```

Pełne testy lokalne:

```powershell
.\scripts\test_local.ps1
```

Skrypt uruchamia lint, pełny zestaw testów, buduje lokalną paczkę Windows i sprawdza jej start.
Gotowy program znajduje się w `dist\HA Windows Bridge`. Żaden z tych kroków nie tworzy
commita, taga ani wydania na GitHubie.

Dokumentacja trwającej modernizacji i lokalnej paczki testowej:
[audyt](docs/MODERNIZATION_AUDIT.md), [architektura](docs/MODERNIZATION_ARCHITECTURE.md),
[wyniki i uruchomienie wersji lokalnej](docs/MODERNIZATION_FINAL_AUDIT.md).
Nie jest to nowe wydanie na GitHubie.

## Bezpośredni kanał Home Assistant

Nakładki mogą docierać lokalnym WebSocketem bez brokera MQTT:

1. Wgraj bieżący katalog `custom_components/ha_windows_bridge` do
   `/config/custom_components/ha_windows_bridge` i ponownie uruchom Home Assistant.
2. W HA wybierz **Ustawienia → Urządzenia i usługi → Dodaj integrację → HA Windows
   Bridge**. Podaj nazwę komputera i dokładne ID widoczne na stronie połączenia aplikacji.
3. W profilu użytkownika HA, na karcie **Bezpieczeństwo**, utwórz długoterminowy token.
4. W aplikacji otwórz **Połączenie → Home Assistant**, zaznacz **Włącz połączenie bezpośrednie**, wpisz
   adres HA z `http://` lub `https://`, wklej token i wybierz **Testuj połączenie**.
5. Włącz **Funkcje → Nakładka → Wiadomości na ekranie**, zapisz ustawienia i uruchom
   usługę.

Przykładowe wywołanie w **Narzędzia deweloperskie → Akcje**:

```yaml
action: ha_windows_bridge.show_overlay
target:
  entity_id: notify.windows_pc_overlay
data:
  title: Test WebSocket
  message: Bezpośrednie połączenie z Home Assistant działa.
  background_effect: liquid
  duration: 10
  show_lifetime: true
  pause_on_hover: true
```

Zastąp `notify.windows_pc_overlay` encją utworzoną przez integrację. Token jest
szyfrowany przez Windows DPAPI i nie trafia do pliku konfiguracji ani eksportu.

Ten kanał obsługuje obecnie nakładki i powiadomienia. Telemetria oraz sterowanie Windows
pozostają dostępne przez MQTT; oba połączenia mogą działać równolegle.

## Aktualizacje i diagnostyka

- **Opublikuj encje ponownie** odświeża urządzenie w Home Assistant bez tworzenia kopii.
- **Eksportuj** zapisuje ustawienia bez hasła MQTT i tokenu Home Assistant.
- **Raport diagnostyczny** usuwa dane logowania i dane połączenia.
- **Wyczyść dane MQTT** usuwa zachowane wpisy utworzone przez aplikację.

## Rozwiązywanie problemów

### Encje są widoczne, ale sterowanie nie działa

Sprawdź integrację MQTT w Home Assistant, połączenie aplikacji i uprawnienia konta MQTT.

### Brakuje części telemetrii

Aplikacja publikuje tylko dane udostępnione przez Windows i sterownik urządzenia.

## Licencja

Copyright © 2026 Grzechu51. Projekt jest udostępniany na warunkach
[GNU Affero General Public License v3.0](LICENSE). Problemy i propozycje można zgłaszać
w [GitHub Issues](https://github.com/Grzechu51/ha-windows-bridge/issues).
