# HA Windows Bridge 2.0.0-alpha.2

Wersja przedpremierowa nowej generacji. Aplikacja Windows i integracja HA powinny pochodzić z tego samego wydania.

## Poprawki

- Przełączniki: płynne rysowanie i brak dodatkowej obwódki po kliknięciu; fokus klawiatury pozostaje widoczny.
- Nakładki: przywrócone tło, prawidłowo cienkie paski postępu i czasu życia.
- Odtwarzacz: okładka jako tło, gradient, źródło, tytuł i czas utworu; nowy lokalny przykład.
- Aplikacje: automatyczne wykrywanie aktywnych sesji audio, ikony EXE, wyrównany suwak, procent, wyciszenie i przełącznik. Nowe programy wymagają włączenia i zapisania przed udostępnieniem w HA.
- Diagnostyka: aktualne CPU, RAM i wątki procesu; odczyt w tle tylko przy otwartej stronie.
- Ustawienia: podpis „Motyw”; usunięte wskazane kafelki informacyjne i opcja zachowania zamknięcia okna. Zamknięcie nadal korzysta z dotychczasowego ustawienia profilu.

## Instalacja

1. Zamknij poprzedni Bridge z zasobnika i uruchom instalator Setup. Alternatywnie wypakuj cały ZIP win64 i uruchom EXE z tego folderu.
2. W HACS wybierz wersje przedpremierowe, pobierz `v2.0.0-alpha.2` i zrestartuj HA.
3. Otwórz Połączenia w aplikacji i skonfiguruj MQTT lub Direct HA. Przy migracji z 0.x nowy profil wymaga ponownego podania połączeń. Profil lokalnej alpha.1 jest zachowany.

[Pełna instrukcja](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0-alpha.2/docs/V2_QUICKSTART.md)

## Ważne

- To alpha, nie zastępuje stabilnego wydania Latest.
- Nowy protokół wymaga integracji HA 2.0. Direct obsługuje nakładki; sensory i audio korzystają z MQTT.
- Liquid Glass używa obecnie natywnego fallbacku Acrylic, bez przechwytywania pulpitu przez GPU.
- Instalator i EXE nie mają podpisu Authenticode. Do paczek dołączono sumy SHA256.
- Walidacja automatyczna nie zastępuje testów rzeczywistego HA, sleep/resume i DWM na wielu monitorach.
