<p align="center">
  <img src="assets/icon.png" alt="HA Windows Bridge" width="128">
</p>

<h1 align="center">HA Windows Bridge</h1>

<p align="center">
  Integracja komputera z Home Assistant przez lokalny broker MQTT.
</p>

<p align="center">
  <a href="https://github.com/Grzechu51/ha-windows-bridge/actions"><img alt="Testy" src="https://github.com/Grzechu51/ha-windows-bridge/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/Grzechu51/ha-windows-bridge/releases"><img alt="Wydanie" src="https://img.shields.io/github/v/release/Grzechu51/ha-windows-bridge?display_name=tag"></a>
  <a href="LICENSE"><img alt="Licencja AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a>
</p>

HA Windows Bridge udostępnia Home Assistantowi sterowanie dźwiękiem, stan programów,
dane systemowe i aktywną sesję multimediów komputera z Windows 10/11. Aplikacja
komunikuje się lokalnie przez MQTT, a instalowana przez HACS integracja tworzy wszystkie
encje pod jednym urządzeniem **HA Windows Bridge**.

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

## Wymagania

- Windows 10 lub Windows 11 w wersji x64;
- Home Assistant z działającą integracją MQTT i brokerem, np. dodatkiem Mosquitto;
- HACS do zalecanej instalacji integracji HA Windows Bridge;
- konto MQTT przeznaczone dla tego komputera.

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
3. Uruchom instalator i opcjonalnie utwórz skrót na pulpicie.
4. Uruchom **HA Windows Bridge** z menu Start.

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
