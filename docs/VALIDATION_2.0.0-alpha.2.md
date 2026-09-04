# Walidacja 2.0.0-alpha.2

- Pełny zestaw pytest: 213 passed.
- Dodatkowe testy skalowania 125%, 150%, 200%: po 13 passed.
- Nowe regresje: fokus przełącznika, rzeczywiście narysowane tło odtwarzacza, grubość pasków, czas utworu, powrót do małej karty, ikony EXE, wyrównanie kontrolek, deduplikacja wykrytych programów, bezpieczeństwo nowych wpisów, lokalne audio niezależne od MQTT, pomiary CPU/RAM i scalanie równoczesnych zapytań.
- Ruff i compileall: PASS.
- Bandit: brak medium/high; jedna uwaga low B311 dla niekryptograficznego jittera reconnect.
- pip-audit: brak znanych podatności; lokalny projekt 2.0.0a2 nie jest audytowany jako pakiet PyPI.
- Rzeczywisty odczyt Windows Audio: znaleziono 2 aktywne sesje, obie ze ścieżką EXE; bez zmieniania głośności.
- Renderowanie Qt obejrzane ze zrzutów testowych; to nie jest pełny test DWM na fizycznych monitorach.
- PyInstaller + smoke-test gotowego EXE: PASS.
- Instalator Inno Setup: kompilacja zakończona poprawnie; nie instalowano go nad działającą aplikacją.
- Oba ZIP-y: poprawna integralność, brak plików cache Pythona. Sumy SHA256 dołączone do wydania.

Nie przeprowadzono instalacji na produkcyjnym HA ani wielogodzinnego testu CPU/RAM. Znane ograniczenia 2.0 opisuje `V2_REBUILD.md`.
