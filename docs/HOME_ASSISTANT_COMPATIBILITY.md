# Home Assistant — zgodność i tożsamość urządzeń

Ta strona opisuje model integracji rozwijany w Phase 6. Stan walidacji i wyniki
przeglądów są zapisane w [raporcie Phase 6](audit-2026-09-05/PHASE6.md).

## Wersje Home Assistant

Minimalna wspierana wersja to **2026.9.0**. Macierz testów obejmuje **2026.9.0**
i **2026.9.3**, potwierdzoną jako bieżące stabilne wydanie 25 września 2026.
Wymagania potwierdzono w metadanych PyPI: [minimum](https://pypi.org/pypi/homeassistant/2026.9.0/json) i [bieżące wydanie](https://pypi.org/pypi/homeassistant/json). Obie wersje wymagają Pythona >=3.14.2; lokalna walidacja używa izolowanych venv
z Pythonem 3.14.7 w Ubuntu-24.04 pod WSL2.

Testy `tests_ha` uruchamiają prawdziwe Home Assistant, jego config flows,
platformy, rejestry i usługi. Testy zastępują granicę sieciową MQTT; wybrane
przypadki usług kontrolują także wynik wysyłki i politykę uprawnień, a przypadki
awarii wstrzykują błędy. To sprawdza
zachowanie integracji w HA, ale nie stanowi testu fizycznego brokera ani
wielogodzinnego działania kompletnej instalacji Windows + HA.

## Identyfikatory i aktualizacja

Phase 6 wprowadza **breaking migration rejestru Home Assistant**. Docelowo jeden
komputer ma jeden wpis integracji, jedno urządzenie i jeden zestaw encji wspólny
dla Direct/MQTT. Stare identyfikatory encji i urządzeń mogą się zmienić; po
migracji trzeba sprawdzić odwołania w automatyzacjach i dashboardach. Ciągłość
historii starych encji nie jest gwarantowana.

Użyteczna konfiguracja starego wpisu jest przenoszona tam, gdzie jej znaczenie
jest jednoznaczne. Stary model może zostać posprzątany dopiero po poprawnym
utworzeniu i zweryfikowaniu modelu docelowego. Nie pozostają dodatkowe urządzenia
Direct ani aliasy popup utrzymywane wyłącznie dla zgodności.

Docelowy wpis używa `device_id` profilu Windows jako `unique_id`, urządzenie
identyfikatora `(ha_windows_bridge, device_id)`, a popup
`<device_id>_windows_overlay`. Przy połączeniu dwóch wpisów ustawienia MQTT mają
pierwszeństwo. Brakujące własne nazwy, obszary i etykiety mogą zostać uzupełnione
ze starego Direct. Przy aktualizacji samego Direct zachowany wpis nadal przechowuje
jego opcje i preferencje; zmiana tożsamości popupu nie wymaga odtwarzania profilu.
Po migracji identyfikator komputera nadal pochodzi z zapisanego profilu Windows
(`device_id`), a zapisane identyfikatory aplikacji i funkcji określają ich
trwałą tożsamość. Zmiana nazwy wyświetlanej nie tworzy nowego komputera ani encji.
Chwilowy brak funkcji albo wyłączenie modułu pozostawia jej encję w rejestrze HA;
po powrocie tej samej funkcji wraca ona pod identyfikatorem modelu docelowego.
To zachowanie jest niezależne od jednorazowego sprzątania starego modelu.

Migracja jest deterministyczna i ma możliwość wznowienia. Konflikt wymagający
świadomego działania użytkownika trafia do Repairs. W razie błędu zachowaj
istniejącą konfigurację i postępuj według komunikatu przed ponowną próbą.

## Granica zgodności protokołów

| Ścieżka | Zachowanie |
| --- | --- |
| MQTT discovery schema 1 | Zachowana obsługa starszej konfiguracji Media Player. |
| MQTT discovery schema 2 | Zachowana obsługa starszych definicji encji. |
| MQTT discovery schema 3 | Walidowane definicje encji i jawna konfiguracja protokołu. |
| MQTT bez opisu protokołu | Starsza publikacja komend; brak potwierdzenia wykonania nie jest gwarancją dostarczenia. |
| MQTT Protocol v2 | Zachowany adapter komend i odpowiedzi podczas aktualizacji istniejących instalacji. |
| MQTT Protocol v3 | Sesja, ograniczone komendy, capabilities i potwierdzenia zgodne z kontraktem v3. |
| Direct WebSocket | Protocol v3; wyłącznie nakładka. Audio i pozostałe funkcje nadal używają MQTT. |

Nie usuwamy adapterów v2 ani starszego discovery, dopóki są potrzebne do
obsługi starszych profili i klientów Windows. Breaking migration rejestru HA jest od tego niezależna. Aktualizacja HA nie wymaga regenerowania
profilu Windows ani zmiany zapisanych identyfikatorów.

## Diagnostyka i obsługa błędów

Diagnostyka integracji udostępnia wyłącznie dozwolone dane strukturalne.
Nie eksportuje tokenów, tematów MQTT, nazw komputera, identyfikatorów
urządzeń/encji/sesji ani treści sensorów i powiadomień.

Usługi nakładki wymagają włączonej encji docelowej i uprawnień użytkownika.
Odczyt treści z innych encji wymaga również uprawnień do ich odczytu.
Rozłączony transport, przekroczenie limitu lub brak potwierdzenia komendy są
błędami wykonania; ponowne wywołanie powinno nastąpić po usunięciu przyczyny.
Wartości liczbowe usług i ich źródeł muszą być skończone. Nieprawidłowy zakres
postępu, `nan`, `inf` albo zbyt duża liczba w atrybucie źródłowym zwracają błąd
walidacji. Komunikaty usług i wykonania poleceń mają tłumaczenia EN/PL.

Repairs wskazuje nazwę wpisu wymagającego uwagi. Konflikt migracji wymaga
sprawdzenia zduplikowanych wpisów i przypisania encji przed przeładowaniem
integracji. Nieukończone sprzątanie oznacza, że model docelowy działa, ale stare
rekordy wymagają ponowienia operacji przez przeładowanie. Zgłoszenie znika po
udanym ponowieniu albo usunięciu danego wpisu integracji.