# Docelowa architektura i kolejność modernizacji

Podstawa: [audyt](MODERNIZATION_AUDIT.md). Implementacja iteracyjna, bez rewrite,
nowego GUI frameworka ani zmiany publicznego protokołu. Własny kod na obecnym PySide6.

## Obecny przepływ i właściciele

```text
app (QApplication, logger, SettingsStore, single instance)
  MainWindow (formularz + lifecycle)
    MQTT bridge -> audio / system / media -> MQTT discovery + stany
    DirectHaBridge -> HA WebSocket subscribe -> UiSignals
    UiSignals -> OverlayManager -> QWidget / DWM / capture
  HA custom integration -> encje + akcje -> MQTT lub event WS
```

Qt widgets są tworzone i zmieniane tylko w wątku GUI. Transporty nie importują GUI.
Adaptery Windows nie powinny znać MQTT ani HA. Discovery/protocol pozostają czystymi
funkcjami. Media ma własną pętlę asyncio; właściciel pętli odpowiada za jej zamknięcie.
Konfiguracja formularza staje się konfiguracją runtime wyłącznie po zatwierdzeniu.

## Struktura docelowa (nie wszystkie pliki muszą powstać od razu)

```text
ha_windows_bridge/
  app.py                         # composition root, bez stylesheet
  gui.py                         # kompatybilny import MainWindow
  ui/
    main_window.py               # shell, podpięcie kontrolerów
    pages/                      # connection, applications, features, logs, settings
    components/                 # title bar, navigation, setting cards
    motion.py                   # duration/easing/reduced motion
    theme.py                    # tokeny + jeden stylesheet
  runtime/                      # lifecycle i ograniczone zadania w tle
  security.py                   # wspólna redakcja sekretów
  overlay.py                    # fasada kompatybilna dla istniejących importów
  overlays/
    manager.py                  # koordynacja Qt, timeout/hover
    card.py                     # rysowanie pojedynczej karty
    models.py                   # normalizacja wejścia bez Qt/Windows
    queue.py                    # priorytety, limity, update/remove
    positioning.py              # czyste obliczenia geometrii
  direct_bridge.py / mqtt_bridge.py
  config.py / data_exchange.py
  audio.py / media.py / system_monitor.py / windows_effects.py
custom_components/ha_windows_bridge/
  config_flow.py / diagnostics.py / entity.py
  platformy i usługi (dotychczasowe nazwy, unique IDs i tematy)
```

Nie tworzyć sztucznego Service/Controller dla każdej funkcji. Wyodrębnienie musi
usunąć zależność, zapewnić właściciela zasobu lub umożliwić test bez GUI.

## Partie i bramki jakości

1. Bezpieczeństwo i komunikacja: redakcja, handshake cleanup, heartbeat, start/stop.
2. Niezawodność: media loop, izolacja sensorów, worker lifecycle; konfiguracja.
3. Nakładki: czysta kolejka/model, wydzielenie karty i managera bez zmiany importów.
4. GUI: wydzielenie stron/komponentów, motyw, wspólny MotionSystem, dostępność.
5. HA: diagnostics, lifecycle subskrypcji i config flow przez oficjalne API.
6. Polish i final audit: tray, aktywne odświeżanie widoku, pełne testy i build.

Po każdej partii: istniejące i nowe pytest, Ruff, import/smoke. Przed wydaniem:
Bandit, build/installer, HA hassfest/HACS w CI i ręczna macierz Windows. Nie publikować
nowego release automatycznie w ramach tego refaktoru; wersja opublikowana pozostaje
nienaruszona. Wyniki testów i niewykonane testy odnotować oddzielnie.

## Kontrakty i decyzje

- Brak zmiany nazw encji, device_id, tematów MQTT, pól akcji lub konfiguracji.
- Bezpośrednie WS nadal obsługuje nakładki; nie udaje alternatywy MQTT dla sensorów.
- Nie dodajemy teraz własnego szyfrowania aplikacyjnego, remote shell/file access,
  ani ACK/dedup zmieniających format publicznych wiadomości.
- Motion: entrance 220 ms, exit 160 ms, reposition/page 180 ms, toggle 120 ms;
  OutCubic / InCubic, bez bounce. Wspólny reduced motion; animacje można przerwać.
- Entrance/exit utrzymuje rozmiar siatki tekstu. Qt steruje zegarem klatek;
  nie obiecywać 144 fps bez pomiaru na danym monitorze.
- Acrylic tylko tam, gdzie obecny adapter ma bezpieczny fallback; Mica i Snap
  wymagają dedykowanej weryfikacji Win32, nie globalnego hacka stylesheet.
- Jeden komponent ustawia wygląd stanu kontrolki; stan disabled nie może ukrywać
  informacji potrzebnej do jej ponownego włączenia. Klawiatura i focus są wymagane.
