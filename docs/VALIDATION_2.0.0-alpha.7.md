# Walidacja 2.0.0-alpha.7

- Pełny zestaw: 272 testy pytest zaliczone. Instalator i oba ZIP-y zbudowane; smoke-test gotowego EXE zakończony powodzeniem. Wersja EXE i manifestu integracji zgodna: alpha.7.
- Archiwum EXE zawiera DXcam, backend DXGI, procesor NumPy i biblioteki NumPy. OpenCV nie jest dołączane ani wykorzystywane do przechwytywania.
- Testy skalowania 125%, 150%, 200%: po 46 zaliczonych; media, wyrównanie kontrolek, minimalne szerokości, cztery warianty animacji i oba motywy.
- Nowe regresje: pauza, przewinięcie i zmiana utworu; zachowanie terminu zamknięcia i pauzy na najechaniu; ochrona odtwarzacza HA przed nadpisaniem sesją Windows; zmiana dostępności długości utworu; brak ponownego dekodowania okładki przy zmianie pozycji; brak restartowania animacji; zatrzymanie odczytu po zamknięciu.
- Regresje interfejsu: skracanie identyfikatorów AUMID do nazw aplikacji, kolorowy stan połączeń, brak oznaczenia wersji rozwojowej, brak dolnej kreski pól i bocznego paska wyboru oraz kompletna spłaszczona klatka animacji bez natywnej warstwy rozmycia.
- Nowe regresje alpha.7: popup szkła pozostaje ukryty do ukończenia przechwycenia tła; pierwsza animowana klatka zawiera gotowe rozmycie i zaokrągloną maskę; Liquid Glass różni się od zwykłego rozmycia; oś czasu nie wchodzi na sektor okładki.
- Ruff: PASS. Bandit: brak problemów medium/high. pip-audit: brak znanych podatności bibliotek; lokalny projekt nie jest pakietem audytowanym w PyPI.
- Rzeczywisty odczyt Windows Media potwierdził aktywną sesję z okładką i niezmienną pozycją przy pauzie. Nie wysyłano poleceń do odtwarzacza użytkownika.
- Pomiar lokalny przechwycenia DXGI i rozmycia obszaru 520×214 px: średnio 2,91 ms, maksimum 22,5 ms, 24 próbki z częstotliwością 4 Hz. CPU procesu około 0,17% całego procesora. To pomiar fragmentu potoku na jednym komputerze, nie całej aplikacji ani gwarancja dla innych monitorów.
- Przegląd MQTT ograniczono do aktualnego komputera i jego prefiksu. Usunięto cztery nieużywane stany retained z lokalną kopią. Rejestr HA zawierał 25 encji zgodnych z aktywną konfiguracją, więc nie usuwano żadnej encji HA. Kopia i prywatne dane audytu nie są częścią paczki ani repozytorium.

Testy Qt używają renderowania offscreen i nie zastępują oceny natywnego DWM na różnych wersjach Windows, przez RDP i na mieszanych monitorach DPI. Nie instalowano aplikacji ani nie restartowano HA użytkownika. Liquid Glass ma ograniczoną częstotliwość i awaryjnie używa rozmycia Windows albo jednolitego tła. Okno Liquid Glass jest wykluczane z przechwytywania ekranu, aby jego własny obraz nie trafiał ponownie do tła; może przez to nie pojawiać się na zrzutach ekranu.
