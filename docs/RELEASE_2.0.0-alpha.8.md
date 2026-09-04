# HA Windows Bridge 2.0.0-alpha.8

- Odtwarzacz ma zawsze stały rozmiar 520 × 214 px, niezależnie od proporcji okładki i długości tytułu. Dłuższy tekst jest skracany w stałym sektorze.
- Zaokrąglenie animowanego popupu jest wymuszane bezpośrednio regionem okna Windows, dzięki czemu pierwsze klatki nie zależą od opóźnionej maski Qt/DWM.
- Usunięto dekoracyjny łuk z Liquid Glass.

- Efekt rozmycia jest przygotowywany, zanim popup stanie się widoczny, dlatego nie pojawia się już prostokątna ani nierozmyta pierwsza klatka.
- Zaokrąglony region okna jest ponownie wymuszany po utworzeniu natywnego okna Windows i przed startem animacji.
- Liquid Glass ma osobne załamanie tła, mocniejszy refleks i większą przezroczystość; zwykłe rozmycie pozostało spokojne i matowe.
- Oś czasu odtwarzacza jest krótsza, zaokrąglona i kończy się w sektorze tekstu zamiast przechodzić przez okładkę.

- Większe sterowanie odtwarzaczem i wyrównane teksty. Okładka płynnie przechodzi w dopasowane kolorystycznie tło.
- Pauza, przewijanie i zmiana utworu w Windows aktualizują widoczną nakładkę bez ponownego wywołania. Aktualizacja nie przedłuża czasu wyświetlania.
- Poprawione rozmycie Windows i Liquid Glass. Przechwytywanie działa tylko przy widocznym Liquid Glass, w tle, z ograniczoną częstotliwością.
- Usunięta osobna natywna warstwa rozmycia. Animacja korzysta z jednej gotowej klatki całego popupu, więc Windows nie może już pokazać prostokątnego tła przed tekstem i kontrolkami.
- Wybór animacji i jej czasu; osobne ustawienia tła oraz długości lokalnych przykładów.
- Ciemniejszy motyw i usunięte wewnętrzne zaokrąglenia pod paskiem tytułu.
- Czytelne kolorowe wskaźniki MQTT i Home Assistant, uproszczone nazwy aplikacji multimedialnych oraz oczyszczona nawigacja i obramowania pól w obu motywach.

## Aktualizacja

Zamknij Bridge z zasobnika i uruchom instalator alpha.8. Profil i istniejące encje pozostają zachowane. Poprawki wyglądu nie wymagają zmiany tokenu ani ponownego dodawania komputera. Do paczki dołączono integrację z ujednoliconym numerem alpha.8.

W **Nakładki** wybierz animację, czas i tło przykładów, kliknij **Zapisz i zastosuj**, następnie pokaż przykład. Test **Odtwarzacz** korzysta z bieżącej sesji Windows.

Wydanie testowe przygotowane lokalnie. Instalator nie jest podpisany cyfrowo. Sumy SHA256 są dołączone do paczek. Pełna instrukcja: `docs/V2_QUICKSTART.md`.
