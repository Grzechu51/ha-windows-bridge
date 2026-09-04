# Uruchomienie 2.0.0-alpha.3

To wydanie przedpremierowe. Przed aktualizacją integracji wykonaj kopię zapasową Home Assistant. Nie uruchamiaj dwóch wersji Bridge jednocześnie.

## Aplikacja Windows

Pobierz [wydanie 2.0.0-alpha.3](https://github.com/Grzechu51/ha-windows-bridge/releases/tag/v2.0.0-alpha.3).
Zamknij działającą wersję Bridge z zasobnika. Uruchom instalator `HA-Windows-Bridge-Setup-2.0.0-alpha.3.exe` albo rozpakuj **cały** ZIP `win64` do osobnego folderu i otwórz `HA Windows Bridge.exe`. Nie przenoś samego EXE bez folderu `_internal`.

Dla uruchomienia z kodu, w PowerShell:

```powershell
cd "F:\Codex\HA MQTT PC"
.\.venv\Scripts\python.exe -m ha_windows_bridge
```

Nowa wersja zapisuje `%LOCALAPPDATA%\HAWindowsBridge\profile-v2.json`. Nie odczytuje automatycznie starego profilu. Sekrety są szyfrowane DPAPI dla bieżącego użytkownika Windows.

1. W **Połączenia** podaj broker MQTT albo włącz połączenie bezpośrednie.
2. W **Sensory i funkcje** włącz potrzebne opcje; dla dysków i urządzeń użyj przycisku wyboru.
3. W **Nakładki** możesz wyświetlić lokalne przykłady bez HA.
4. Wybierz **Zapisz i zastosuj**, a następnie **Przegląd → Uruchom**. Opcjonalnie włącz automatyczne łączenie.

Na stronie **Aplikacje** program automatycznie wykrywa aktywne sesje audio i ich ikony. Nowo wykryte programy nie są automatycznie udostępniane w HA: włącz wybrane przełączniki i zapisz. Jeśli programu nie ma, uruchom w nim dźwięk albo wybierz **Dodaj program…**.

W **Diagnostyce** znajdziesz aktualne CPU, RAM i liczbę wątków Bridge. CPU jest liczone względem całego procesora; pierwsza próbka pojawia się po około 2 sekundach. Odczyty zatrzymują się po ukryciu okna.

## Aktualizacja integracji przez HACS

W HACS przy HA Windows Bridge wybierz **⋮ → Pobierz ponownie (Redownload) → Potrzebujesz innej wersji? (Need a different version?)** i wskaż `v2.0.0-alpha.3`. Po pobraniu uruchom HA ponownie. Jeśli wersji nie widać, użyj **⋮ → Aktualizuj informacje (Update information)**. W HACS 2 dostęp do aktualizacji beta kontroluje też encja przełącznika wersji przedpremierowych dla danego repozytorium. W razie potrzeby dodaj `Grzechu51/ha-windows-bridge` jako repozytorium niestandardowe typu **Integracja**.

Opis opcji: [wybór wersji w HACS](https://hacs.xyz/docs/use/repositories/dashboard/#downloading-a-specific-version-of-a-repository), [przełącznik wersji przedpremierowych](https://hacs.xyz/docs/use/entities/switch/).

Pakiet `HA-Integration` w wydaniu służy instalacji ręcznej; przy HACS nie trzeba go rozpakowywać ani kopiować folderów.

## MQTT

W HA potrzebne są działający broker i integracja MQTT. Bridge 2.0 publikuje discovery własnej integracji. Zainstaluj folder `custom_components/ha_windows_bridge` z tej samej gałęzi 2.0, zrestartuj HA i dodaj wykryty komputer.

Nie instaluj alpha nad produkcyjną integracją bez kopii zapasowej HA. Stare wydanie 0.x nie realizuje nowego protokołu ACK.

## Bezpośrednie połączenie WebSocket

1. W HA zainstaluj **integrację 2.0** i uruchom HA ponownie.
2. W aplikacji skopiuj **ID urządzenia** ze strony Połączenia.
3. W HA: **Ustawienia → Urządzenia i usługi → Dodaj integrację → HA Windows Bridge**, wpisz nazwę komputera i to ID.
4. Utwórz w profilu użytkownika HA długoterminowy token. Użytkownik tokenu musi mieć prawo sterowania encją popupu tego komputera.
5. W aplikacji wpisz adres, np. `http://192.168.0.60:8123`, oraz token. Nie wpisuj końcówki `/api/websocket` — aplikacja dodaje ją sama.
6. Włącz połączenie bezpośrednie, zapisz i uruchom usługi.

Kanał Direct 2.0 służy nakładkom. Audio i sensory korzystają z MQTT. Nie wpisuj tokenu do automatyzacji ani w adresie URL. Po zmianie danych logowania użyj **Połącz ponownie**.

## Automatyzacja HA

Użyj akcji **HA Windows Bridge: Wyświetl nakładkę Windows** i wybierz encję popupu komputera. Pola encji, kamery, obrazu i odtwarzacza są w tej akcji, nie w selektorze zapisanych szablonów. Wersja 2.0 nie zawiera lokalnego konfiguratora zapisanych popupów.

ACK potwierdza obsługę polecenia przez Bridge; nakładka może czekać w kolejce. Pełny ekran lub blokada sesji mogą wstrzymać wyświetlenie zgodnie z ustawieniami.

## Konfiguracja i diagnostyka

- **Ustawienia → Eksportuj ustawienia**: plik bez sekretów.
- **Importuj ustawienia**: wczytuje profil 2.0 do formularza; dopiero zapis go stosuje. Zmiana serwera wymaga ponownego podania hasła/tokenu.
- **Przywróć domyślne ustawienia**: zachowuje dane połączeń; zmiana wymaga zapisania.
- **Diagnostyka → Eksportuj raport**: informacje o wersji, systemie i błędach, bez tokenów i haseł.

## Testy bez uruchamiania usług

```powershell
.\scripts\test_local.ps1 -SkipBuild
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe main.py --smoke-test
Remove-Item Env:QT_QPA_PLATFORM
```

Nie pozostawiaj `QT_QPA_PLATFORM=offscreen`, jeżeli chcesz zobaczyć normalne okno aplikacji.
