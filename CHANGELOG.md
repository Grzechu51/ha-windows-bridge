# Changelog

## 1.3.2

- uproszczony formularz nakładki w Home Assistant: pojedyncze przełączniki, natywny
  wybór ikon MDI, automatyczny lub ręczny rozmiar i krycie tła od 0 do 100%;
- usunięty powielony styl neutralny oraz duplikaty ustawień nakładki z aplikacji Windows;
- osobna telemetria RAM z pamięcią zajętą, dostępną i całkowitą; czas działania
  przeniesiony do połączonego modułu stanu Windows;
- wyraźnie przygaszone listy dysków i urządzeń po wyłączeniu modułu oraz poprawiona
  ikona połączenia w jasnym motywie;
- biblioteka ikon dołączona do gotowej aplikacji i skrócona dokumentacja użytkownika.

## 1.3.1

- nowoczesna nakładka bez zastępczej ikony, z widocznymi stylami, poprawnym tekstem,
  konfigurowalnym przyciskiem zamknięcia i zamykaniem po kliknięciu;
- domyślne położenie, monitor, rozmiar i krycie nakładki przeniesione do aplikacji oraz
  rzeczywisty czas i postęp aktywnej sesji multimediów;
- czytelniejsze pola akcji Home Assistant bez ręcznego wyboru układu oraz źródła
  postępu i czasu z encji wraz z mapowaniem własnego zakresu;
- uproszczone Audio bez automatycznego ściszania i regulacji czułości mikrofonu;
- edycja pełnych profilów miksu i możliwość uruchamiania jednego profilu przez kilka
  programów;
- łączny sensor sesji audio Windows oraz poprawione ikony sensorów sesji aplikacji;
- wybór monitorowanych woluminów i osobne sensory zajętego oraz wolnego miejsca;
- filtrowanie urządzeń Windows według stanu aktywne/nieaktywne, z pominięciem
  technicznych interfejsów HID, usług Bluetooth, koncentratorów i wirtualnych drukarek;
- poprawiony zapis ustawień po usunięciu funkcji automatycznego ściszania;
- poprawione uruchamianie w zasobniku wyłącznie przy autostarcie Windows;
- zweryfikowane lokalne ikony integracji i udokumentowane ograniczenie ikony na liście
  HACS wynikające z błędu jego frontendu.

## 1.3.0

- nowoczesna nakładka bez zastępczej ikony, z przyciskiem zamknięcia przypiętej karty,
  wyborem monitora oraz rzeczywistym czasem i postępem aktywnej sesji multimediów;
- źródła postępu i czasu z encji Home Assistant wraz z mapowaniem własnego zakresu;
- podgląd bieżącego poziomu mikrofonu przy regulacji czułości bez odpytywania po
  zminimalizowaniu okna aplikacji;
- edycja profilów audio i możliwość uruchamiania jednego profilu przez kilka programów;
- łączny sensor sesji audio Windows oraz poprawione ikony sensorów sesji aplikacji;
- wybór monitorowanych woluminów i osobne sensory zajętego oraz wolnego miejsca;
- poprawione i przycięte ikony aplikacji, instalatora, HACS i lokalnej integracji.

## 1.2.1

- przeprojektowana nakładka Windows z widoczną ramką, cieniem, kolorowym obramowaniem i
  mniejszym odstępem od wybranego rogu ekranu;
- usunięty boczny pasek nakładki, lekko zwiększona przezroczystość i dodany układ Media;
- komplet lokalnych ikon i logo integracji dla jasnego oraz ciemnego interfejsu HA;
- naprawiony odczyt aktywnego planu zasilania na Windows używającym kodowania OEM;
- pojedynczy błąd opcjonalnego monitora nie powoduje już odpytywania go w każdej iteracji;
- zabezpieczony odczyt baterii i sporadyczne nieprawidłowe PID aktywnego okna.

## 1.2.0

- nowa, przełączana sekcja **System i dyski** ze stanem Windows Update, zasilania,
  miejscem, transferem, SMART i temperaturą;
- osobne, automatycznie wykrywane moduły telemetrii CPU i GPU bez pustych encji;
- **Audio** z obsługą wielu sesji, balansem, profilami i duckingiem z regulacją czułości;
- wybrane urządzenia Plug and Play jako encje obecności;
- bezpieczna, obramowana nakładka Windows z kolejką, aktualizacją po ID, obrazem, QR
  i postępem;
- osobne zakładki i przełączniki wszystkich nowych modułów w interfejsie PL/EN;
- dodatkowa walidacja MQTT, obrazów i poleceń oraz testy regresji nowych funkcji;
- poprawione pakowanie bibliotek Qt na Windows oraz automatyczny test startu gotowego EXE;
- czyste zastępowanie bibliotek aplikacji podczas aktualizacji instalatorem.

## 1.1.0

- poprawiony ciemny motyw i kompletny jasny motyw;
- usunięty powielony status z górnego paska oraz skrócony opis aplikacji;
- kompaktowe pola języka, motywu i interwału odczytu;
- osobne czyszczenie danych MQTT i odinstalowanie;
- opcjonalne, ograniczone akcje blokady, uśpienia, restartu i wyłączenia;
- powiadomienia Windows przez encję `notify` Home Assistant;
- eksport i import konfiguracji bez hasła MQTT;
- raport diagnostyczny z redakcją danych połączenia i sekretów;
- automatyczne sprawdzanie oficjalnych wydań GitHub;
- opcjonalne podpisywanie EXE i instalatora przez Authenticode;
- rozszerzone testy Discovery, poleceń MQTT, motywów i bezpieczeństwa.
