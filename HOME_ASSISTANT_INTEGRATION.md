# Integracja HA Windows Bridge

Integracja dodaje do Home Assistant funkcje włączone w aplikacji Windows. Korzysta z
istniejącej integracji MQTT i nie przechowuje hasła do brokera.

## Instalacja

1. W HACS otwórz **⋮ → Custom repositories**.
2. Dodaj `https://github.com/Grzechu51/ha-windows-bridge` jako **Integration**.
3. Pobierz **HA Windows Bridge** i uruchom Home Assistant ponownie.
4. Uruchom połączenie MQTT w aplikacji Windows.
5. Potwierdź wykryty komputer w **Ustawienia → Urządzenia i usługi**.

Przy instalacji ręcznej skopiuj `custom_components/ha_windows_bridge` do
`config/custom_components/ha_windows_bridge` i uruchom HA ponownie.

## Dostępne funkcje

- głośność, wyciszenie, stan i osobny Media Player każdego wybranego programu;
- Media Player aktywnej sesji Windows;
- stan Windows, CPU, RAM, GPU i wybrane dyski;
- wybrane urządzenia Windows;
- wybór wyjścia audio;
- bezpieczne akcje komputera;
- powiadomienia i nakładka ekranowa.

Wyłączenie funkcji w aplikacji usuwa odpowiadające jej encje po zapisaniu ustawień.

## Nakładka

Wygląd popupów konfiguruje się teraz w aplikacji Windows, w sekcji
**Funkcje → Nakładka → Projektant popupów**. Projektant pokazuje efekt na żywo i zapisuje
wiele nazwanych wzorów osobno dla każdego komputera. Po synchronizacji integracja tworzy
encję `select` **Zapisany popup** z listą tych wzorów.

Akcja **Wybierz opcję** dostępna dla tej encji jedynie zmienia aktywny projekt. Następnie
w automatyzacji dodaj akcję **HA Windows Bridge: Wyświetl zapisany popup**. Jej formularz
pozwala wskazać encje tytułu, wartości/wiadomości, postępu i czasu, odtwarzacz
`media_player`, encję `camera` albo `image` oraz opcjonalny adres obrazu.

Rekomendowana akcja automatyzacji to:

```yaml
action: ha_windows_bridge.show_saved_overlay
data:
  template_entity: select.pc_windows_saved_popup
  title: Pralka
  message_entity: sensor.pralka_pozostaly_czas
  progress_entity: sensor.pralka_postep
```

`template_entity` jednocześnie wskazuje komputer i aktualnie wybrany projekt. Opcjonalne
`template_id` pozwala wybrać inny zapisany projekt tylko dla danego wywołania. Tytuł,
wiadomość, postęp i czas mogą pochodzić ze stanu albo wskazanego atrybutu encji. Zmiana
opcji encji `select` jest odsyłana do aplikacji i zapamiętywana lokalnie.

Rozbudowana akcja `show_overlay` nadal działa jako interfejs zaawansowany i zachowuje
zgodność z dotychczasowymi automatyzacjami.

Aktualne multimedia wyświetlisz poleceniem:

```yaml
action: ha_windows_bridge.show_overlay
target:
  entity_id: notify.pc_windows_overlay
data:
  notification_id: now_playing
  media: true
  pinned: true
  show_close_button: true
  size_mode: auto
  background_effect: liquid
  edge_offset: 16
```

Pole **Odtwarzacz Home Assistant** pozwala wskazać dowolną dostępną encję
`media_player`. Nakładka pokazuje nazwę odtwarzacza, tytuł, wykonawcę, postęp oraz
okładkę po prawej stronie. Kolory powierzchni i tekstu są dobierane z grafiki z
zachowaniem kontrastu. Bez wyboru encji opcja bieżących multimediów używa sesji z
komputera docelowego. Tryb automatyczny dopasowuje kartę do treści i ignoruje pola
`width` oraz `height`. Pole efektu tła oferuje powierzchnię jednolitą, standardowe
rozmycie i **Liquid Glass**. Standardowe rozmycie korzysta z Desktop Acrylic, a Liquid
Glass preferuje DXGI Desktop Duplication i adaptacyjne odświeżanie. W trybie zdalnym
albo przy problemach z wydajnością aplikacja wybiera bezpieczny efekt zastępczy.
`edge_offset` odsuwa kartę od wybranych krawędzi ekranu. Ikonę wybiera się z biblioteki
MDI HA. Priorytet porządkuje kolejkę, `show_lifetime` pokazuje pozostały czas, a
`pause_on_hover` wstrzymuje zamknięcie po najechaniu.

Układ `status` z opcją `display_mode: parallel` pokazuje jednocześnie do czterech
niezależnych kart, na przykład baterię, CPU i RAM. Każda karta musi mieć własne
`notification_id`; przy braku miejsca karty automatycznie przechodzą do kolejnego rzędu.
Układ `badge` jest jeszcze mniejszy i tworzy kapsułkę z ikoną, miniaturą lub krótką
wartością. Kilka znaczników z `display_mode: parallel` może utworzyć pasek wskaźników
podobny do interfejsu telewizora.

`update_overlay` aktualizuje wiadomość o tym samym ID, `remove_overlay` ją usuwa, a
`clear_overlay` czyści kolejkę.

Nakładkę można też dodać ręcznie jako bezpośredni endpoint WebSocket. W konfiguracji
integracji podaj ID urządzenia widoczne w aplikacji Windows, a w aplikacji skonfiguruj
adres Home Assistant i długoterminowy token. Tryb bezpośredni obsługuje nakładki oraz
powiadomienia, a także synchronizację zapisanych popupów. Pozostałe encje nadal używają
MQTT.

Po restarcie HA dodaj integrację ręcznie, wybierz jej encję `notify` jako cel akcji
`ha_windows_bridge.show_overlay`, a następnie uruchom usługę w aplikacji Windows.
Połączenie jest inicjowane wychodząco przez komputer do `/api/websocket`; nie wymaga
otwierania portu przychodzącego na komputerze.

## Usuwanie

1. W aplikacji wybierz **Wyczyść dane MQTT**.
2. Usuń wpis HA Windows Bridge w **Ustawienia → Urządzenia i usługi**.
3. Usuń integrację w HACS i uruchom Home Assistant ponownie.
