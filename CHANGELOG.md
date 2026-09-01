# Changelog

## 0.10.0-beta.1 - 2026-09-01

- konfigurowalna nakładka Windows z automatycznym lub ręcznym rozmiarem, kolejką,
  przypinaniem, wyborem monitora i odstępem od krawędzi ekranu;
- dynamiczne standardowe rozmycie oraz warstwowy Liquid Glass z automatycznym trybem
  zgodności dla zdalnego pulpitu, problemów z przechwytywaniem i wolniejszego sprzętu;
- natywny Desktop Acrylic przez DWM dla standardowego rozmycia oraz Desktop Duplication
  na GPU dla Liquid Glass z adaptacyjnym odświeżaniem i trybem oszczędzania energii;
- automatyczne układy treści, układ kamery priorytetowej, kanały, priorytety, opcjonalny
  pasek czasu życia i zatrzymanie odliczania po najechaniu;
- obsługa Per-Monitor V2 DPI, zmiany konfiguracji ekranów i wzorce do lokalnych testów;
- opcjonalny bezpośredni kanał WebSocket Home Assistant dla nakładek, niewymagający
  brokera MQTT i przechowujący token za pomocą Windows DPAPI;
- automatyczny kontrast tekstu i delikatna warstwa ochronna dopasowane do jasności tła;
- płynniejsze pojawianie, zanikanie i zmiana rozmiaru z poszanowaniem systemowego
  ograniczenia animacji;
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
