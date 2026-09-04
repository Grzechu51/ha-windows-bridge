# HA Windows Bridge 2.0.0-alpha.3

Poprawki wyglądu na podstawie działającej wersji 0.9.0.

- **Media Player:** pełna okładka po prawej bez kadrowania; tło dobierane z lewej krawędzi okładki; oryginalne łagodne przejście; dopasowane kolory źródła, tytułu, opisu, czasu i pasków. Dobór jasnego/ciemnego tekstu z kontrolą kontrastu.
- **Ikony programów:** źródło wysokiej rozdzielczości, usunięcie pustych marginesów i stały rozmiar 46 px logicznych niezależnie od DPI. Czytelne ikony także przy wyłączonym udostępnianiu. Cache ogranicza ponowne przetwarzanie.
- **Brakujące ikony:** odświeżanie po aktualizacji programu i odczyt metadanych skonfigurowanych, uruchomionych aplikacji bez sesji audio. Odświeżenie ikony nie zmienia zatwierdzonej ścieżki zdalnego uruchamiania.
- **Ustawienia:** wspólny wiersz dla opisów, przełączników i wyboru motywu; usunięte miejsce na pusty opis; wyrównanie pionowe i jednakowe minimalne wysokości. Wyłączona opcja nie wyszarza jej opisu jak niedostępnej funkcji.

## Instalacja

Zamknij Bridge w zasobniku i uruchom instalator Setup albo rozpakuj cały ZIP win64. W HACS wybierz **Pobierz ponownie → Inna wersja → v2.0.0-alpha.3** i zrestartuj HA. Profil poprzednich wersji 2.0 alpha zostaje zachowany.

[Instrukcja MQTT i WebSocket](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0-alpha.3/docs/V2_QUICKSTART.md)

To prerelease; stabilne Latest pozostaje bez zmian. Instalator nie ma podpisu Authenticode. Sumy SHA256 są dołączone. Testy renderowania Qt nie zastępują weryfikacji DWM i rzeczywistego HA na docelowym sprzęcie. Liquid Glass nadal korzysta z fallbacku Acrylic.
