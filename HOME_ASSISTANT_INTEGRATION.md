# Integracja HA Windows Bridge dla Home Assistant

Integracja 1.0 tworzy pod jednym urządzeniem wszystkie encje udostępniane przez aplikację
Windows: regulatory, przełączniki, sensory, przyciski, wybór wyjścia audio i Media Player.
Do komunikacji używa istniejącej integracji MQTT Home Assistant, dlatego nie wymaga
ponownego wpisywania adresu brokera ani hasła.

## Instalacja przez HACS

[![Otwórz repozytorium w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

1. Otwórz w HACS menu **⋮ → Custom repositories**.
2. Dodaj **https://github.com/Grzechu51/ha-windows-bridge** jako **Integration**.
3. Wyszukaj **HA Windows Bridge**, wybierz **Download** i uruchom Home Assistant ponownie.
4. Skonfiguruj i uruchom aplikację HA Windows Bridge na komputerze.
5. Potwierdź automatycznie wykryty komputer w **Ustawienia → Urządzenia i usługi**.

## Instalacja ręczna

1. Skopiuj katalog **custom_components/ha_windows_bridge** do
   **config/custom_components/ha_windows_bridge**.
2. Uruchom Home Assistant ponownie.
3. Uruchom połączenie MQTT w aplikacji Windows.
4. Potwierdź wykrytą integrację.

## Encje

Integracja może utworzyć następujące platformy:

- number: głośność główna, mikrofon, aktywna aplikacja i wybrane programy;
- switch: wyciszenie główne, mikrofonu i programów;
- binary_sensor: połączenie, uruchomienie programu, aktywność mikrofonu, pełny ekran,
  aktywność komputera i blokada Windows;
- sensor: aktywna aplikacja i okno, bezczynność, CPU, RAM, uptime oraz GPU;
- button: dozwolony przez użytkownika start lub łagodne zamknięcie programu;
- select: domyślne wyjście audio;
- media_player: aktywna sesja multimediów Windows z miniaturą.

Wyłączenie funkcji w aplikacji Windows usuwa jej definicję z wpisu integracji po
zapisaniu ustawień. Identyfikatory pozostałych encji nie zmieniają się.

## Media Player

Media Player może udostępniać tytuł, wykonawcę, album, program źródłowy, czas,
pozycję, głośność, wyciszenie, okładkę lub miniaturę oraz komendy obsługiwane przez
aktywną sesję Windows.

Obraz jest ograniczony do 1 MB i weryfikowany jako PNG, JPEG, GIF albo WebP. Nie każda
aplikacja przekazuje Windowsowi wszystkie metadane i komendy.

## Usuwanie

1. W aplikacji Windows wybierz **Wyczyść MQTT i odinstaluj**.
2. Usuń wpis HA Windows Bridge w **Ustawienia → Urządzenia i usługi**.
3. Usuń integrację w HACS i uruchom Home Assistant ponownie.
4. Jeśli ma to być pełny reset, usuń **%LOCALAPPDATA%\HAWindowsBridge**; operacja usuwa
   konfigurację, zaszyfrowane hasło i logi.
