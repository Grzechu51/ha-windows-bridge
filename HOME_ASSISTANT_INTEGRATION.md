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

- głośność, wyciszenie i stan wybranych programów;
- Media Player aktywnej sesji Windows;
- stan Windows, CPU, RAM, GPU i wybrane dyski;
- wybrane urządzenia Windows;
- wybór wyjścia audio;
- bezpieczne akcje komputera;
- powiadomienia i nakładka ekranowa.

Wyłączenie funkcji w aplikacji usuwa odpowiadające jej encje po zapisaniu ustawień.

## Nakładka

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
rozmycie i **Liquid Glass**. Oba efekty odświeżają obraz pulpitu, a Liquid Glass
automatycznie przechodzi na lżejszy efekt w trybie zdalnym albo przy problemach z
wydajnością. `edge_offset` odsuwa kartę od wybranych krawędzi ekranu. Ikonę wybiera
się z biblioteki MDI HA.

`update_overlay` aktualizuje wiadomość o tym samym ID, `remove_overlay` ją usuwa, a
`clear_overlay` czyści kolejkę.

## Usuwanie

1. W aplikacji wybierz **Wyczyść dane MQTT**.
2. Usuń wpis HA Windows Bridge w **Ustawienia → Urządzenia i usługi**.
3. Usuń integrację w HACS i uruchom Home Assistant ponownie.
