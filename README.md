<p align="center">
  <img src="https://raw.githubusercontent.com/Grzechu51/ha-windows-bridge/main/assets/icon.png" alt="HA Windows Bridge" width="128">
</p>

<h1 align="center">HA Windows Bridge</h1>

<p align="center">Sterowanie komputerem z Windows w Home Assistant przez lokalne MQTT.</p>

HA Windows Bridge łączy aplikację Windows z integracją Home Assistant. Pokazuje tylko
funkcje włączone w aplikacji, dzięki czemu urządzenie w HA pozostaje czytelne.

## Możliwości

- głośność i wyciszenie Windows oraz wybranych programów;
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

### Wersja testowa 0.10.0-beta.3

W HACS włącz dla tego repozytorium obsługę wersji **pre-release/beta**, a następnie
wybierz **Redownload → Need a different version? → v0.10.0-beta.3**. Aplikację Windows
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
- **Audio** — Media Player aktywnej sesji Windows, balans kanałów i liczba sesji.
- **Urządzenia** — wybór aktywnych lub nieaktywnych urządzeń widocznych w Windows.
- **Nakładka** — w aplikacji projektujesz i zapisujesz gotowe popupy z podglądem na
  żywo. Home Assistant wybiera zapisany wzór i może podmienić jego treść danymi encji.

Wyłączenie modułu usuwa jego encje po zapisaniu i ponownym opublikowaniu konfiguracji.

## Media Player

Włącz **Media Player** w aplikacji, aby dodać do Home Assistant aktywną sesję
multimediów Windows. Dostępne informacje i przyciski zależą od programu odtwarzającego.

## Nakładka Windows

Najwygodniejszy sposób konfiguracji:

1. Otwórz w aplikacji **Funkcje → Nakładka → Projektant popupów**.
2. Wybierz istniejący wzór albo utwórz nowy. Każda zmiana wyglądu jest pokazywana na
   pulpicie po krótkim opóźnieniu.
3. Ustaw układ, efekt tła, pozycję, rozmiar, czas, zachowanie oraz treść i wybierz
   **Zapisz popup**.
4. Po połączeniu z HA pojawi się encja `select` z listą wzorów zapisanych na tym
   komputerze. Akcja **Wybierz opcję** tylko zmienia aktywny wzór. Do wyświetlenia
   karty dodaj osobną akcję **HA Windows Bridge: Wyświetl zapisany popup**
   (`ha_windows_bridge.show_saved_overlay`).

Przykład, w którym zapisany wygląd pozostaje bez zmian, a tekst i postęp pochodzą z
encji Home Assistant:

```yaml
action: ha_windows_bridge.show_saved_overlay
data:
  template_entity: select.pc_windows_saved_popup
  title: Stan baterii
  message_entity: sensor.laptop_battery
  progress_entity: sensor.laptop_battery
```

W edytorze wizualnym tej akcji można bez YAML wybrać encje tytułu i
wartości/wiadomości, encję postępu, czas, odtwarzacz `media_player`, aktualny obraz z
encji `camera` lub `image`, a także adres obrazu. Wygląd nadal pochodzi z projektu
zapisanego w aplikacji Windows.

Pole `template_id` jest opcjonalne. Bez niego używany jest wzór aktualnie wybrany w
encji `select`. Możesz też wskazać encję lub jej atrybut jako źródło tytułu, wiadomości,
postępu i czasu. Dzięki temu rozbudowana konfiguracja wizualna pozostaje w aplikacji,
a automatyzacja HA zawiera tylko źródła danych.

Poniższa akcja `show_overlay` pozostaje dostępna jako tryb zaawansowany i dla zgodności
z istniejącymi automatyzacjami.

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

Pole **Efekt tła** pozwala wybrać jednolitą powierzchnię, natywny Windows Desktop
Acrylic albo warstwowy efekt **Liquid Glass**. Liquid Glass przechwytuje pulpit przez
DXGI Desktop Duplication i automatycznie ogranicza częstotliwość odświeżania, gdy obraz
się nie zmienia. Przy zdalnym pulpicie, błędach sterownika lub słabszym sprzęcie używany
jest bezpieczny tryb zgodności. Pole **Odstęp od krawędzi** odsuwa widoczną kartę w głąb
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

Zmiany można sprawdzać bez commita, taga i GitHuba. W zakładce **Funkcje → Nakładka**
włącz wiadomości ekranowe i użyj projektanta popupów. Podgląd aktualizuje się na żywo,
a po jego wyłączeniu nakładka znika. Zapisane projekty można selektywnie importować i
eksportować jako JSON, bez przenoszenia całej konfiguracji programu.

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

## Bezpośredni kanał Home Assistant

Nakładki mogą docierać lokalnym WebSocketem bez brokera MQTT:

1. Wgraj bieżący katalog `custom_components/ha_windows_bridge` do
   `/config/custom_components/ha_windows_bridge` i ponownie uruchom Home Assistant.
2. W HA wybierz **Ustawienia → Urządzenia i usługi → Dodaj integrację → HA Windows
   Bridge**. Podaj nazwę komputera i dokładne ID widoczne na stronie połączenia aplikacji.
3. W profilu użytkownika HA, na karcie **Bezpieczeństwo**, utwórz długoterminowy token.
4. W aplikacji otwórz **Połączenie**, zaznacz **Włącz połączenie bezpośrednie**, wpisz
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
Bezpośredni kanał synchronizuje również katalog zapisanych popupów i encję wyboru;
nie wymaga do tego MQTT.

Ten kanał obsługuje obecnie nakładki i powiadomienia. Telemetria oraz sterowanie Windows
pozostają dostępne przez MQTT; oba połączenia mogą działać równolegle.

## Aktualizacje i diagnostyka

- **Opublikuj encje ponownie** odświeża urządzenie w Home Assistant bez tworzenia kopii.
- **Eksportuj** zapisuje ustawienia bez hasła MQTT.
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
