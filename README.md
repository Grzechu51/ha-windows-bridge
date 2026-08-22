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
dane systemowe, bezpieczne akcje komputera i aktywną sesję multimediów z Windows 10/11.
Aplikacja komunikuje się lokalnie przez MQTT, a integracja instalowana przez HACS
umieszcza wszystkie włączone encje pod jednym urządzeniem **HA Windows Bridge**.

## Najważniejsze możliwości

- główna głośność Windows, wyciszenie i regulacja aktywnej aplikacji;
- osobne regulatory, wyciszenie i stan uruchomienia wybranych programów;
- opcjonalny zdalny start i łagodne zamknięcie programu;
- głośność, wyciszenie i aktywność mikrofonu;
- wybór domyślnego wyjścia audio;
- aktywna aplikacja i okno, pełny ekran, bezczynność oraz blokada sesji;
- CPU, RAM, czas pracy systemu i opcjonalna telemetria kart NVIDIA;
- natywny `media_player` z metadanymi, pozycją, komendami i miniaturą;
- opcjonalne przyciski blokady, uśpienia, restartu, wyłączenia i anulowania;
- powiadomienia Windows wysyłane z Home Assistant;
- eksport i import konfiguracji oraz raport diagnostyczny bez danych logowania;
- polski i angielski interfejs, ciemny i jasny motyw, autostart i zasobnik systemowy;
- automatyczne sprawdzanie dostępności nowego wydania na oficjalnym GitHubie.

Każda rozszerzona funkcja jest opcjonalna. Dane systemowe, zdalne akcje, powiadomienia
oraz zdalne uruchamianie i zamykanie programów są domyślnie wyłączone.

## Jak działa integracja

Aplikacja publikuje jeden ograniczony i walidowany opis urządzenia pod:

```text
ha-windows-bridge/devices/<device_id>
```

Integracja HA Windows Bridge odbiera go przez działającą integrację MQTT Home Assistant
i tworzy platformy `number`, `switch`, `binary_sensor`, `sensor`, `button`,
`select`, `notify` oraz `media_player`. Zmiana włączonych funkcji aktualizuje ten
sam wpis, a stabilne identyfikatory zapobiegają powstawaniu kopii encji.

## Wymagania

- Windows 10 lub Windows 11 x64;
- Home Assistant z aktywną integracją MQTT;
- HACS do zalecanej instalacji integracji HA Windows Bridge;

## Przygotowanie MQTT w Home Assistant

Broker działa po stronie Home Assistant, dlatego aplikacja Windows nie może bezpiecznie
zainstalować go ani samodzielnie utworzyć poświadczeń administratora. Home Assistant
potrafi natomiast automatycznie skonfigurować oficjalną aplikację Mosquitto podczas
dodawania integracji MQTT.

1. W Home Assistant otwórz **Ustawienia → Urządzenia i usługi → Dodaj integrację**.
2. Wybierz **MQTT** i skorzystaj z proponowanej konfiguracji Mosquitto Broker albo podaj
   dane własnego brokera.
3. Jeżeli używasz oficjalnej aplikacji Mosquitto, dodaj w jej konfiguracji osobny login,
   np. `ha_windows_bridge_pc`, z silnym i unikalnym hasłem.
4. Uruchom ponownie Mosquitto po zmianie konfiguracji.
5. Do HA Windows Bridge wpisz adres IP lub nazwę hosta Home Assistant, port, nowy login
   i hasło. Nie używaj konta `root`.

Aktualną instrukcję konfiguracji znajdziesz w
[dokumentacji MQTT Home Assistant](https://www.home-assistant.io/integrations/mqtt/)
oraz [dokumentacji Mosquitto Broker](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md).

Dla własnego brokera Mosquitto warto ograniczyć konto do topiców tego programu. Przy
domyślnym głównym topicu punktem wyjścia jest:

```text
user ha_windows_bridge_pc
topic read homeassistant/status
topic readwrite ha-windows-bridge/#
```

Jeżeli zmienisz główny topic lub prefix Home Assistant, dostosuj ACL. Port 1883 bez TLS
jest przeznaczony wyłącznie do zaufanej sieci lokalnej. Nie wystawiaj niezabezpieczonego
brokera do Internetu; poza LAN użyj VPN albo poprawnie skonfigurowanego TLS.

## Instalacja integracji Home Assistant

[![Otwórz repozytorium w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

1. W HACS otwórz **⋮ → Custom repositories**.
2. Dodaj **https://github.com/Grzechu51/ha-windows-bridge** jako **Integration**.
3. Wyszukaj **HA Windows Bridge**, wybierz **Download** i uruchom Home Assistant ponownie.

Instalacja ręczna polega na skopiowaniu katalogu
`custom_components/ha_windows_bridge` do
`config/custom_components/ha_windows_bridge`, a następnie ponownym uruchomieniu
Home Assistant.

## Instalacja aplikacji Windows

1. Otwórz [najnowsze wydanie](https://github.com/Grzechu51/ha-windows-bridge/releases/latest).
2. Pobierz **HA-Windows-Bridge-Setup-1.1.0.exe**.
3. Porównaj sumę SHA-256 z plikiem **SHA256SUMS-1.1.0.txt**.
4. Uruchom instalator i opcjonalnie utwórz skrót na pulpicie.
5. Uruchom **HA Windows Bridge** z menu Start.

Archiwum **HA-Windows-Bridge-1.1.0-win64.zip** jest wersją przenośną. Po rozpakowaniu
trzeba zachować cały katalog wraz z folderem `_internal`.

## Pierwsza konfiguracja

1. Wpisz adres, port, użytkownika i hasło brokera MQTT.
2. Kliknij **Testuj połączenie**.
3. W **Aplikacje** wykryj uruchomione programy i włącz potrzebne pozycje.
4. W **Funkcje** włącz tylko dane i akcje, które mają być dostępne w Home Assistant.
5. Kliknij **Zapisz i zastosuj**, a następnie uruchom usługę.
6. Home Assistant pokaże wykrytą integrację **HA Windows Bridge**. Potwierdź dodanie
   komputera.

Przycisk **Opublikuj encje ponownie** wysyła ponownie bieżący opis urządzenia. Nie
tworzy nowych identyfikatorów ani duplikatów encji.

## Media Player

Odtwarzacz używa Windows Global System Media Transport Controls. Obsługuje tylko
metadane i komendy udostępnione systemowi przez aktywny program. Miniatura pochodzi
bezpośrednio z sesji Windows, jest weryfikowana i udostępniana przez bezpieczny proxy
obrazu Home Assistant.

Pojedynczy obraz jest ograniczony do 1 MB. Akceptowane są PNG, JPEG, GIF i WebP o
zgodnym typie MIME oraz sygnaturze pliku. Brak miniatury nie blokuje odtwarzacza.

## Bezpieczne akcje i powiadomienia

Aplikacja nie wykonuje dowolnych poleceń z MQTT. Obsługiwana jest stała lista akcji:
blokada, uśpienie, restart, wyłączenie i anulowanie. Restart i wyłączenie mają
30-sekundowe opóźnienie, podczas którego można nacisnąć **Cancel Power Action**.
Funkcja jest domyślnie wyłączona.

Encja `notify` przyjmuje jedynie tytuł i tekst. Długość jest ograniczona, retained
commands są ignorowane, a wiadomość pojawia się jako zwykłe powiadomienie zasobnika
Windows.

## Konfiguracja, diagnostyka i czyszczenie

- **Eksportuj** zapisuje konfigurację bez hasła MQTT.
- **Importuj** zachowuje aktualnie zapisane hasło i wymaga potwierdzenia.
- **Raport diagnostyczny** ukrywa hasła, tokeny, broker, użytkownika i główny topic.
- **Wyczyść dane MQTT** usuwa znane zachowane topiki bez odinstalowania aplikacji.
- **Odinstaluj aplikację** osobno pyta, czy przed odinstalowaniem wyczyścić MQTT.

Hasło MQTT jest zabezpieczone przez Windows DPAPI i może zostać odszyfrowane tylko przez
tego samego użytkownika Windows. Dane aplikacji są przechowywane w
`%LOCALAPPDATA%\HAWindowsBridge`.

## Aktualizacje i podpisywanie

Aplikacja może automatycznie sprawdzać oficjalne wydania GitHub i otworzyć stronę
nowszej wersji. Nie pobiera ani nie uruchamia instalatora bez zgody użytkownika.
\

## Rozwiązywanie problemów

### Stany docierają, ale sterowanie nie działa

Jeżeli Home Assistant pokazuje `Cannot publish to topic...`, jego własna integracja
MQTT nie jest aktywna lub poprawnie skonfigurowana. Uruchom ją w
**Ustawienia → Urządzenia i usługi → MQTT**, a następnie przeładuj MQTT i HA Windows
Bridge albo uruchom Home Assistant ponownie. Sam działający broker nie wystarcza.

### Sensory NVIDIA mają stan „nieznany”

Aplikacja korzysta z `nvidia-smi.exe` instalowanego ze sterownikiem NVIDIA. Jeśli
narzędzie nie istnieje lub sterownik nie udostępnia konkretnej wartości, odpowiedni
sensor pozostanie nieznany bez wpływu na pozostałe funkcje.

## Ograniczenia

- multimedia zależą od funkcji udostępnianych systemowi Windows przez dany program;
- telemetria GPU obsługuje obecnie NVIDIA przez `nvidia-smi`;
- zdalne zamknięcie programu wysyła łagodne żądanie tylko do widocznych okien;
- aplikacja i integracja wymagają dostępności lokalnego brokera MQTT;
- sprawdzanie aktualizacji wymaga dostępu do API GitHub.

## Licencja i zgłaszanie problemów

Copyright © 2026 Grzechu51.

Projekt jest udostępniany na warunkach
[GNU Affero General Public License v3.0](LICENSE). Zasady odpowiedzialnego zgłaszania
podatności opisuje [SECURITY.md](SECURITY.md).
