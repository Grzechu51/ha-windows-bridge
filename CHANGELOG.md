# Changelog

## 0.10.0-beta.4 - 2026-09-02

- każda włączona aplikacja audio otrzymuje dodatkową encję `media_player` z dwukierunkową
  regulacją głośności, wyciszeniem oraz stanem uruchomienia; dotychczasowe encje
  `number`, `switch` i `binary_sensor` pozostają dostępne;

## 0.10.0-beta.3 - 2026-09-02

- usunięte pole kanału z formularzy akcji Home Assistant oraz uproszczone globalne
  czyszczenie nakładek;
- akcja zapisanego popupu otrzymała czytelne selektory encji treści, wartości, postępu,
  czasu, odtwarzacza, kamery i obrazu oraz możliwość pobrania grafiki z adresu URL;

## 0.10.0-beta.2 - 2026-09-02

- konfigurowalna nakładka Windows z automatycznym lub ręcznym rozmiarem, kolejką,
  przypinaniem, wyborem monitora i odstępem od krawędzi ekranu;
- dynamiczne standardowe rozmycie oraz warstwowy Liquid Glass z automatycznym trybem
  zgodności dla zdalnego pulpitu, problemów z przechwytywaniem i wolniejszego sprzętu;
- natywny Desktop Acrylic przez DWM dla standardowego rozmycia oraz Desktop Duplication
  na GPU dla Liquid Glass z adaptacyjnym odświeżaniem i trybem oszczędzania energii;
- automatyczne układy treści, układ kamery priorytetowej, priorytety, opcjonalny
  pasek czasu życia i zatrzymanie odliczania po najechaniu;
- obsługa Per-Monitor V2 DPI, zmiany konfiguracji ekranów i podgląd projektu na żywo;
- opcjonalny bezpośredni kanał WebSocket Home Assistant dla nakładek, niewymagający
  brokera MQTT i przechowujący token za pomocą Windows DPAPI;
- automatyczny kontrast tekstu i delikatna warstwa ochronna dopasowane do jasności tła;
- płynniejsze pojawianie, zanikanie i zmiana rozmiaru z poszanowaniem systemowego
  ograniczenia animacji;
- lokalny projektant popupów z podglądem na żywo, zapisem wielu wzorów i synchronizacją
  ich katalogu przez MQTT albo bezpośredni WebSocket;
- selektywny import i eksport zapisanych popupów oraz pełna, przeszukiwalna
  przeglądarka ikon MDI z podglądem ikon;
- uporządkowany projektant popupów: osobny odstęp między akcjami, podgląd na żywo
  w prawym dolnym rogu, animowane suwaki zamiast checkboxów, brak przypadkowej
  zmiany pól rolką i poprawiony obszar pól liczbowych;
- przywracanie domyślnych opcji programu bez usuwania danych połączenia ani ID
  urządzenia oraz uproszczona sekcja ustawień;
- usunięte stopniowe narastanie przezroczystości podczas pojawiania się nakładki,
  wstrzymane przechwytywanie tła na czas animacji i wyłączona dodatkowa ramka DWM;
- usunięcie wielowątkowej konwersji klatek DXGI, która mogła niepotrzebnie obciążać
  wszystkie rdzenie procesora podczas działania Liquid Glass;
- encja wyboru zapisanego popupu oraz uproszczona akcja HA pozwalająca podłączać encje
  do gotowego projektu bez ponownego ustawiania całego wyglądu;
- poprawione centrowanie małych znaczników oraz przeorganizowany ekran bezpośredniego
  połączenia z czytelnym stanem i pogrupowanymi ustawieniami;
- karta multimediów z pełną okładką po prawej, dopasowanym kolorem i płynnym gradientem;
- możliwość prezentowania na nakładce dowolnego odtwarzacza dostępnego w Home Assistant;
- lokalny skrypt walidacyjny, testy wzorców nakładki i dodatkowe zabezpieczenia procesu
  budowania paczek instalacyjnych.

To wydanie jest wersją testową. Przed przejściem na wydanie stabilne wymagane są testy
na różnych konfiguracjach monitorów, DPI, kart graficznych i wersjach Windows.

## 0.9.0 - 2026-08-29

- pierwsze publiczne wydanie aplikacji Windows i integracji Home Assistant;
- integracja MQTT z multimediami Windows, audio, telemetrią systemu, dyskami,
  urządzeniami, zasilaniem oraz bezpiecznymi akcjami komputera;
- podstawowa obsługa powiadomień i nakładki ekranowej.
