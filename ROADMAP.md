# HA Windows Bridge — lista rozwoju

Ten dokument zbiera kierunki rozwoju projektu. Nie jest obietnicą terminu ani zakresu
konkretnego wydania. Każda nowa funkcja powinna być opcjonalna, domyślnie bezpieczna,
przetłumaczona na polski i angielski oraz nie może pogarszać działania podstawowego
mostu MQTT.

## Zrealizowane w wersji 1.2.0

### Stan Windows i dysków

- wolne i zajęte miejsce na dyskach;
- stan SMART i przewidywane problemy, jeśli sprzęt udostępnia wiarygodne dane;
- aktywność, transfer i temperatura dysków;
- stan Windows Update i informacja o wymaganym restarcie;
- plan zasilania, bateria laptopa i podłączenie zasilacza;
- osobne przełączniki publikowania grup danych do Home Assistant.

### Audio

- obsługa wielu sesji tego samego programu;
- profile i reguły głośności dla programów;
- balans kanałów oraz szybkie przełączanie głośniki/słuchawki;
- automatyczne ściszanie pozostałych aplikacji podczas rozmowy z regulacją czułości.

Routing pojedynczej obcej aplikacji na osobne wyjście nie jest oznaczony jako gotowy,
ponieważ Windows nie udostępnia dla niego stabilnego publicznego API. Profile przełączają
bezpiecznie domyślne wyjście całego systemu.

### Urządzenia jako encje

- wykrywanie podłączenia i odłączenia urządzeń USB, Bluetooth i audio;
- obecność słuchawek, kontrolera, kamery, drukarki, dysku i innych urządzeń;
- encje stanu i zdarzenia możliwe do wykorzystania w automatyzacjach.

Poziom baterii komputera jest częścią stanu Windows. Baterie akcesoriów nie są jeszcze
publikowane, ponieważ klasy urządzeń Bluetooth i HID udostępniają je niespójnie.

### Windows Overlay

Nakładka inspirowana projektem TvOverlay, ale przeznaczona dla Windows:

- zwykłe i przypięte komunikaty nad innymi oknami;
- tekst, ikona, obraz, kod QR i pasek postępu;
- wybór monitora, narożnika, rozmiaru, czasu i przezroczystości;
- presety wyglądu oraz tryb nieprzechwytujący kliknięć;
- wysyłanie z Home Assistant oraz MQTT;
- kolejka, aktualizowanie i usuwanie komunikatu po jego identyfikatorze;
- brak wstrzykiwania kodu do gier; gwarantowane działanie przede wszystkim w trybie
  okienkowym i bez ramek, żeby nie powodować konfliktów z anti-cheat.

## Integracje API — niewdrożone

Architektura opcjonalnych dostawców, aby awaria lub zmiana zewnętrznego API nie wpływała
na podstawową obsługę Windows i MQTT. Pierwsze sensowne kandydatury:

- OBS Studio WebSocket: scena, nagrywanie, transmisja, mikrofon i przyciski sterujące;
- Spotify Web API: odtwarzanie, urządzenie, utwór, playlisty i rozszerzone metadane;
- Steam Web API: aktualna gra, status, ostatnie gry, czas gry i osiągnięcia;
- qBittorrent WebUI API: transfer, aktywne zadania, pauza i wznowienie;
- GitHub REST API: status Actions, pull requesty, issues, powiadomienia i wydania;
- OpenAI Admin Usage API: opcjonalne koszty i użycie API, bez udawania limitu
  subskrypcji Codex/ChatGPT;
- Jellyfin lub Kodi: sesje odtwarzania i podstawowe sterowanie;
- lokalne usługi WSL, Docker i OBS jako osobna grupa integracji komputera.

Sekrety API nie mogą być przesyłane przez MQTT ani zapisywane jawnym tekstem. Integracje
chmurowe powinny korzystać z minimalnych uprawnień, bezpiecznego magazynu poświadczeń i
jasnego przycisku odłączenia konta.

## Zrealizowane w wersji 1.2.0 — telemetria

### Telemetria CPU i GPU

- procesory: temperatura, taktowanie, pobór mocy i dodatkowe dane dostępne na danym
  sprzęcie;
- karty NVIDIA i AMD: dostępne obciążenie, temperatura, moc, zegary, wentylator i VRAM;
- źródła niewymagające dodatkowej usługi: liczniki wydajności i WMI Windows;
- opcjonalne rozszerzenie temperatury i poboru mocy przez działający już
  LibreHardwareMonitor lub OpenHardwareMonitor;
- aplikacja musi wykrywać możliwości sprzętu i nie tworzyć encji, dla których nie potrafi
  uzyskać danych;
- brak obowiązkowej instalacji ciężkiego programu monitorującego tylko dla tej funkcji.

## Dalsze propozycje — do decyzji

### Profile komputera

Profile Praca, Gry, Film i Noc łączące urządzenie audio, głośność, uruchomione programy,
monitor oraz wybrane działania Home Assistant.

### Centrum stanu komputera

Jedna czytelna strona z kondycją połączenia, błędami urządzeń, miejscem na dysku,
aktualizacjami, wymaganym restartem i wskazówkami rozwiązania problemu.

### Szybki panel w zasobniku

Małe okno do zmiany profilu, urządzenia audio i głośności, uruchomienia ulubionych
programów oraz kilku wybranych akcji Home Assistant bez otwierania głównego okna.

### Skróty globalne

Konfigurowalne skróty do profili, wyciszenia wybranej aplikacji, przełączenia wyjścia
audio, pokazania nakładki i uruchomienia bezpiecznej akcji.

### Reguły lokalne bez Home Assistant

Proste reguły typu „gdy uruchomi się gra, włącz profil Gry” albo „po podłączeniu słuchawek
ustaw je jako wyjście”. Reguły działają lokalnie także podczas awarii MQTT.

### Sterowanie monitorami

Jasność, wygaszanie, źródło HDMI/DisplayPort, HDR i częstotliwość odświeżania, zależnie
od możliwości monitora i DDC/CI.

### Diagnostyka automatyczna

Test MQTT, audio, uprawnień, autostartu, telemetrii i integracji zewnętrznych zakończony
prostym raportem „działa / wymaga uwagi” bez haseł i tokenów.

### Lokalny interfejs CLI i API

Udokumentowane polecenia do odczytu stanu i wywoływania wyłącznie zatwierdzonych akcji.
Domyślnie API powinno nasłuchiwać tylko na `localhost`, wymagać tokenu i mieć osobny
przełącznik w ustawieniach.

### System modułów

Izolowane moduły dla API i sprzętu, z kontrolą wersji, uprawnień oraz możliwością
wyłączenia lub usunięcia bez naruszania głównej aplikacji.
