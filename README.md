<p align="center">
  <img src="assets/icon.png" alt="HA Windows Bridge" width="128">
</p>

<h1 align="center">HA Windows Bridge</h1>

<p align="center">
  Integracja komputera z Windows z Home Assistant przez lokalny broker MQTT.
</p>

<p align="center">
  <a href="https://github.com/Grzechu51/ha-windows-bridge/actions"><img alt="Testy" src="https://github.com/Grzechu51/ha-windows-bridge/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/Grzechu51/ha-windows-bridge/releases"><img alt="Wydanie" src="https://img.shields.io/github/v/release/Grzechu51/ha-windows-bridge?display_name=tag"></a>
  <a href="LICENSE"><img alt="Licencja AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a>
</p>

HA Windows Bridge udostępnia Home Assistantowi sterowanie dźwiękiem, stan programów,
dane systemowe i aktywną sesję multimediów komputera z Windows 10/11. Aplikacja Windows
komunikuje się lokalnie przez MQTT, a instalowana przez HACS integracja tworzy wszystkie
encje pod jednym urządzeniem **HA Windows Bridge**.

Instalator zawiera środowisko uruchomieniowe i wymagane biblioteki. Użytkownik końcowy
nie musi instalować Pythona ani ręcznie kopiować katalogów programu.

## Najważniejsze możliwości

- główna głośność Windows, wyciszenie i regulacja aktywnej aplikacji;
- osobne regulatory, wyciszenie i stan uruchomienia wybranych programów;
- opcjonalny, kontrolowany zdalny start i łagodne zamknięcie programu;
- głośność, wyciszenie i aktywność mikrofonu;
- wybór domyślnego wyjścia audio;
- aktywna aplikacja i okno, pełny ekran, bezczynność oraz blokada sesji;
- CPU, RAM, czas pracy systemu i opcjonalna telemetria kart NVIDIA;
- natywny media_player z tytułem, wykonawcą, pozycją, komendami i miniaturą;
- polski i angielski interfejs, autostart oraz praca w zasobniku systemowym.

Każda funkcja jest opcjonalna. Dodatkowe dane oraz zdalne uruchamianie i zamykanie
programów są domyślnie wyłączone.

## Jak działa wersja 1.0

Wersja 1.0 nie tworzy już osobnych encji należących do standardowej integracji MQTT.
Aplikacja publikuje jedno ograniczone i walidowane ogłoszenie urządzenia pod:

~~~text
ha-windows-bridge/devices/<device_id>
~~~

Integracja HA Windows Bridge odbiera ogłoszenie przez skonfigurowaną w Home Assistant
integrację MQTT i tworzy platformy number, switch, binary_sensor, sensor, button, select
oraz media_player. Regulatory, sensory i odtwarzacz są widoczne w jednym wpisie
integracji i pod jednym urządzeniem.

Zmiana włączonych funkcji lub aplikacji aktualizuje ten sam wpis. Stabilne identyfikatory
zapobiegają tworzeniu kopii encji, a definicje wyłączonych funkcji są usuwane z rejestru.

## Wymagania

- Windows 10 lub Windows 11 w wersji x64;
- Home Assistant z działającą integracją MQTT i brokerem, np. dodatkiem Mosquitto;
- HACS do zalecanej instalacji integracji HA Windows Bridge;
- konto MQTT przeznaczone dla tego komputera.

## Czysta migracja z 0.9 do 1.0

Wersja 1.0 zmienia właściciela encji z integracji MQTT na HA Windows Bridge. Zalecana
jest jednorazowa czysta migracja:

1. W starej aplikacji Windows otwórz **Ustawienia** i wybierz
   **Wyczyść MQTT i odinstaluj**. Pozwól aplikacji usunąć retained topiki przed
   uruchomieniem deinstalatora.
2. W Home Assistant przejdź do **Ustawienia → Urządzenia i usługi** i usuń istniejący
   wpis **HA Windows Bridge**, jeśli był dodany.
3. W HACS usuń starą wersję integracji HA Windows Bridge i uruchom Home Assistant ponownie.
4. Jeśli w integracji MQTT nadal widać stare urządzenie lub encje, usuń je po zakończeniu
   czyszczenia brokera.
5. Dla całkowicie świeżej konfiguracji usuń katalog
   **%LOCALAPPDATA%\HAWindowsBridge**. Ten krok bezpowrotnie usuwa konfigurację,
   zaszyfrowane hasło, historię topiców i logi, więc wykonaj wcześniej kopię potrzebnych danych.
6. Zainstaluj integrację 1.0 przez HACS, uruchom ponownie Home Assistant, a następnie
   zainstaluj aplikację Windows 1.0 i skonfiguruj ją od początku.

Nie instaluj 1.0 na działającej 0.9 bez wcześniejszego czyszczenia, ponieważ retained
definicje starego MQTT Discovery mogą pozostać w brokerze jako duplikaty.

## Instalacja integracji Home Assistant

[![Otwórz repozytorium w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

1. W HACS otwórz menu **⋮ → Custom repositories**.
2. Dodaj **https://github.com/Grzechu51/ha-windows-bridge** jako **Integration**.
3. Wyszukaj **HA Windows Bridge**, wybierz **Download** i uruchom Home Assistant ponownie.

Instalacja ręczna polega na skopiowaniu katalogu
**custom_components/ha_windows_bridge** do **config/custom_components**, a następnie
ponownym uruchomieniu Home Assistant.

## Instalacja aplikacji Windows

1. Otwórz [najnowsze wydanie](https://github.com/Grzechu51/ha-windows-bridge/releases/latest).
2. Pobierz **HA-Windows-Bridge-Setup-1.0.0.exe**.
3. Porównaj sumę SHA-256 z plikiem **SHA256SUMS-1.0.0.txt**.
4. Uruchom instalator i opcjonalnie utwórz skrót na pulpicie.
5. Uruchom **HA Windows Bridge** z menu Start.

Archiwum **HA-Windows-Bridge-1.0.0-win64.zip** jest wersją przenośną. Po rozpakowaniu
należy zachować cały katalog razem z folderem **_internal**.

Instalator nie jest obecnie podpisany płatnym certyfikatem Code Signing, dlatego
Windows SmartScreen może pokazać ostrzeżenie. Pobieraj pliki wyłącznie z oficjalnego
wydania i zawsze sprawdzaj sumę SHA-256.

## Pierwsza konfiguracja

1. Wpisz adres, port, użytkownika i hasło brokera MQTT.
2. Kliknij **Testuj połączenie**.
3. W zakładce **Aplikacje** wykryj uruchomione programy i włącz potrzebne pozycje.
4. W zakładce **Funkcje** włącz wyłącznie dane, które mają być widoczne w Home Assistant.
5. Kliknij **Zapisz i zastosuj** i uruchom usługę.
6. Home Assistant pokaże wykrytą integrację **HA Windows Bridge**. Potwierdź dodanie
   komputera. Wszystkie włączone encje pojawią się pod tym samym urządzeniem.

Przycisk **Opublikuj encje ponownie** wysyła ponownie aktualny spis encji integracji.
Nie tworzy nowych identyfikatorów ani kopii istniejących encji.

## Media Player

Odtwarzacz używa Windows Global System Media Transport Controls. Obsługuje tylko
metadane i komendy udostępnione przez aktywny program. Miniatura pochodzi bezpośrednio
z sesji Windows, jest przechowywana w pamięci integracji i udostępniana przez proxy
obrazu Home Assistant.

Pojedynczy obraz jest ograniczony do 1 MB. Akceptowane są wyłącznie dane PNG, JPEG,
GIF lub WebP o zgodnym typie MIME i sygnaturze pliku. Brak miniatury nie blokuje
pozostałych funkcji odtwarzacza.

## Bezpieczeństwo MQTT

Utwórz osobne konto brokera dla każdego komputera. Dla domyślnej konfiguracji 1.0
wystarczający punkt wyjścia ACL Mosquitto to:

~~~text
user ha_windows_bridge_pc
topic read homeassistant/status
topic readwrite ha-windows-bridge/#
~~~

Jeżeli zmienisz główny topic, odpowiednio zawęź drugą regułę. Wersja 1.0 nie potrzebuje
stałego prawa zapisu do homeassistant/#.

Port 1883 bez TLS jest odpowiedni wyłącznie w zaufanej sieci lokalnej. Dla połączeń
poza taką siecią użyj TLS, zwykle na porcie 8883, VPN i poprawnej weryfikacji
certyfikatu. Nie wystawiaj niezabezpieczonego brokera bezpośrednio do Internetu.

Hasło MQTT jest szyfrowane przez Windows DPAPI i może je odszyfrować tylko ten sam
użytkownik Windows. Konfiguracja oraz rotowane logi znajdują się w
**%LOCALAPPDATA%\HAWindowsBridge**.

## Uruchomienie ze źródeł

Python 3.11 lub nowszy jest wymagany wyłącznie do pracy ze źródłami:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe main.py
~~~

Budowanie wersji przenośnej, integracji i instalatora:

~~~powershell
.\build.ps1 -Installer
~~~

Skrypt uruchamia testy, generuje ikonę, buduje aplikację i tworzy plik sum SHA-256.
Wymagany jest Inno Setup 7 dostępny jako **iscc.exe** albo w **tools/InnoSetup/7.0.2**.

## Ograniczenia

- multimedia zależą od funkcji udostępnianych systemowi Windows przez konkretny program;
- telemetria GPU obsługuje NVIDIA przez nvidia-smi;
- zdalne zamknięcie wysyła łagodne żądanie tylko do widocznych okien i nie wymusza
  zakończenia procesu;
- aplikacja i integracja wymagają dostępności lokalnego brokera MQTT.

## Licencja i zgłaszanie problemów

Copyright © 2026 Grzechu51.

Projekt jest udostępniany na warunkach [GNU Affero General Public License v3.0](LICENSE).
Zasady odpowiedzialnego zgłaszania podatności opisuje [SECURITY.md](SECURITY.md).
