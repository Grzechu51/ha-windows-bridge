# Integracja HA Windows Bridge dla Home Assistant

Integracja tworzy pod jednym urządzeniem wszystkie encje udostępniane przez aplikację
Windows. Do komunikacji używa istniejącej integracji MQTT Home Assistant, dlatego nie
przechowuje adresu brokera ani hasła.

## Instalacja przez HACS

[![Otwórz repozytorium w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

1. Otwórz w HACS **⋮ → Custom repositories**.
2. Dodaj **https://github.com/Grzechu51/ha-windows-bridge** jako **Integration**.
3. Wyszukaj **HA Windows Bridge**, wybierz **Download** i uruchom Home Assistant ponownie.
4. Uruchom połączenie w aplikacji Windows.
5. Potwierdź wykryty komputer w **Ustawienia → Urządzenia i usługi**.

Najpierw musi działać integracja **MQTT** Home Assistant oraz lokalny broker. Samo
zainstalowanie HA Windows Bridge nie instaluje brokera.

## Instalacja ręczna

1. Skopiuj `custom_components/ha_windows_bridge` do
   `config/custom_components/ha_windows_bridge`.
2. Uruchom Home Assistant ponownie.
3. Uruchom usługę MQTT w aplikacji Windows.
4. Potwierdź automatycznie wykrytą integrację.

## Obsługiwane encje

- `number`: głośność główna, mikrofon, aktywna aplikacja i wybrane programy;
- `switch`: wyciszenie główne, mikrofonu i programów;
- `binary_sensor`: połączenie, uruchomienie programu, aktywność mikrofonu,
  pełny ekran, aktywność komputera i blokada Windows;
- `sensor`: aktywna aplikacja i okno, bezczynność, CPU, RAM, uptime oraz GPU;
- `button`: start lub zamknięcie programu oraz opcjonalne akcje komputera;
- `select`: domyślne wyjście audio;
- `notify`: kontrolowane powiadomienia zasobnika Windows;
- `media_player`: aktywna sesja multimediów Windows z miniaturą.

Wyłączenie funkcji w aplikacji usuwa jej encję po zapisaniu i ponownym opublikowaniu
opisu urządzenia. Identyfikatory pozostałych encji nie zmieniają się.

## Media Player

Media Player może udostępniać tytuł, wykonawcę, album, program źródłowy, czas, pozycję,
głośność, wyciszenie, okładkę lub miniaturę oraz komendy obsługiwane przez aktywną sesję
Windows. Obraz jest ograniczony do 1 MB i weryfikowany jako PNG, JPEG, GIF albo WebP.

## Akcje systemowe

Akcje systemowe są domyślnie wyłączone. Aplikacja przyjmuje tylko stałą listę poleceń:
blokada, uśpienie, restart, wyłączenie i anulowanie. Restart i wyłączenie są opóźnione
o 30 sekund. Integracja nie udostępnia encji do wykonywania dowolnych komend.

## Usuwanie

1. W **Ustawieniach** aplikacji wybierz **Wyczyść dane MQTT**.
2. Opcjonalnie wybierz osobno **Odinstaluj aplikację**.
3. Usuń wpis HA Windows Bridge w **Ustawienia → Urządzenia i usługi**.
4. Usuń integrację w HACS i uruchom Home Assistant ponownie.
