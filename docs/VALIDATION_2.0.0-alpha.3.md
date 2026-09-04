# Walidacja 2.0.0-alpha.3

- Pełny zestaw: 228 testów pytest zaliczonych.
- Skalowanie 125%, 150%, 200%: po 22 testy zaliczone.
- Nowe regresje: paleta pobierana z lewej krawędzi okładki, jasny/ciemny tekst i kontrast, pełna okładka bez kadrowania, faktyczny kolor wyrenderowanego tła, wyrównanie opisów i przełączników, wspólny wiersz motywu, logiczny rozmiar ikon, crop pustych marginesów, cache i odświeżanie metadanych bez zmiany zatwierdzonego zdalnego EXE, ikony uruchomionych programów bez sesji audio.
- Ruff: PASS. Bandit: brak medium/high; istniejąca uwaga low dotycząca niekryptograficznego jittera reconnect.
- pip-audit: brak znanych podatności zależności; lokalny projekt 2.0.0a3 nie jest audytowany jako pakiet PyPI.
- Renderowanie Qt obejrzano ze zrzutów testowych. Pełna walidacja DWM/mieszanych monitorów i rzeczywistego HA nie jest zastąpiona tymi testami.

Wzorzec wyglądu: `v0.9.0:ha_windows_bridge/overlay.py`, funkcje `_media_palette`, `_average_artwork_color`, `_right_artwork_rect` i gradient `OverlayCard.paintEvent`. Mechanizm przeniesiono do nowego silnika bez przywracania starego managera.

Ikony są skalowane w pikselach fizycznych i otrzymują współczynnik DPR, aby na ekranie zachować 46 px logicznych. [Dokumentacja Qt](https://doc.qt.io/qt-6/qpixmap.html#deviceIndependentSize).
