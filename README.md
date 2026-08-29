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
- **Nakładka** — w aplikacji wybierasz tylko monitor i zgodę na pełny ekran. Treść,
  wygląd, rozmiar, czas i sposób zamknięcia ustawiasz w akcji Home Assistant.

Wyłączenie modułu usuwa jego encje po zapisaniu i ponownym opublikowaniu konfiguracji.

## Media Player

Włącz **Media Player** w aplikacji, aby dodać do Home Assistant aktywną sesję
multimediów Windows. Dostępne informacje i przyciski zależą od programu odtwarzającego.

## Nakładka Windows

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

Pole **Efekt tła** pozwala wybrać jednolitą powierzchnię, standardowe rozmycie albo
warstwowy efekt **Liquid Glass**. Widoczność powierzchni reguluje **Krycie tła**.
Standardowe rozmycie i Liquid Glass odświeżają pulpit pod widoczną kartą. Przy zdalnym
pulpicie, błędach przechwytywania lub zbyt wolnym renderowaniu Liquid Glass
automatycznie użyje lżejszego rozmycia. Pole **Odstęp od krawędzi** odsuwa widoczną
kartę w głąb ekranu. Ikonę wybiera się z biblioteki MDI Home Assistant.

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
