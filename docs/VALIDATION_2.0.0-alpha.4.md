# Walidacja 2.0.0-alpha.4

- Pełny zestaw: 246 testów pytest zaliczonych.
- Skalowanie 125%, 150%, 200%: po 38 testów zaliczonych. Sprawdzone minimalne szerokości, wyrównanie kontrolek, nowy Przegląd i diagnostyka.
- Ruff: PASS. Bandit: brak problemów medium/high; istniejący low dotyczy niekryptograficznego jittera ponawiania połączenia.
- pip-audit: brak znanych podatności zależności; lokalny projekt nie jest audytowany jako pakiet PyPI.
- Rzeczywisty odczyt Windows Media: dostępne API, aktywna sesja, metadane i okładka. Nie zapisano treści multimediów ani poświadczeń do raportu.
- Sprawdzono odróżnienie poprawnego uwierzytelnienia HA od odmowy subskrypcji Bridge. Sprawdzono przypadek wyłączonego udostępniania nakładek i braku encji popupu.
- Regresje obejmują zachowanie działających/zatrzymanych usług po zapisie, przywrócenie usług po błędzie zapisu, historię diagnostyki przed otwarciem okna, asynchroniczny podgląd rzeczywistej sesji multimedialnej, brak sesji i anulowanie oczekującego podglądu.
- Testy autoryzacji integracji obejmują wpis MQTT i Direct, inne urządzenie, inny właścicielski wpis encji, wyłączoną encję, brak uprawnień i trwające uruchomienie integracji.
- Test wspólnego MQTT/Direct potwierdza kierowanie tylko popupów przez WebSocket, niezależność ACK audio i powrót nowych popupów do MQTT po rozłączeniu Direct.

Testy integracji używają atrap API HA. Pełne połączenie po poprawce wymaga aktualizacji integracji na docelowym HA i ponownego uruchomienia HA; nie wykonano automatycznej zmiany instalacji ani restartu serwera użytkownika. Testy Qt nie zastępują pełnego testu DWM i mieszanych monitorów.
