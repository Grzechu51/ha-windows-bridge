# Uruchomienie 2.0 alpha lokalnie

Ta wersja nie jest jeszcze opublikowana w GitHub Releases. Nie trzeba jej instalować ani kopiować nad działający program.

## Aplikacja Windows

Zamknij działającą wersję Bridge z zasobnika. W PowerShell:

```powershell
cd "F:\Codex\HA MQTT PC"
.\.venv\Scripts\python.exe -m ha_windows_bridge
```

Nowa wersja zapisuje `%LOCALAPPDATA%\HAWindowsBridge\profile-v2.json`. Nie odczytuje automatycznie starego profilu. Sekrety są szyfrowane DPAPI dla bieżącego użytkownika Windows.

1. W **Połączenia** podaj broker MQTT albo włącz połączenie bezpośrednie.
2. W **Sensory i funkcje** włącz potrzebne opcje; dla dysków i urządzeń użyj przycisku wyboru.
3. W **Nakładki** możesz wyświetlić lokalne przykłady bez HA.
4. Wybierz **Zapisz i zastosuj**, a następnie **Przegląd → Uruchom**. Opcjonalnie włącz automatyczne łączenie.

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
