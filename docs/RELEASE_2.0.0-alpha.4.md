# HA Windows Bridge 2.0.0-alpha.4

- Naprawione połączenie bezpośrednie dla komputera dodanego przez MQTT: nie wymaga drugiego wpisu Direct. Uprawnienia nadal są sprawdzane dla konkretnej encji popupu.
- Przegląd i ustawienia połączeń na jednej stronie, ze wspólnym, rzeczywistym statusem połączenia.
- Zapis ustawień wznawia wcześniej uruchomione usługi, niezależnie od opcji automatycznego łączenia.
- Test odtwarzacza pokazuje aktualną sesję Windows i okładkę, bez paska pozostałego czasu do zamknięcia.
- Diagnostyka pokazuje stan usług, CPU/RAM/wątki oraz historię startu, zapisu i połączeń. Błędy konfiguracji nie są już przedstawiane jako błędny token.
- Wyłączone nakładki są opisane wprost; aplikacja nie próbuje wtedy uruchamiać niepotrzebnego połączenia Direct.

## Aktualizacja

Zaktualizuj **aplikację Windows i integrację HA** do alpha.4. Zamknij Bridge z zasobnika przed uruchomieniem instalatora. W HACS wybierz alpha.4 i uruchom HA ponownie, następnie w aplikacji kliknij **Połącz ponownie**. Nie zmieniaj prawidłowego tokenu i nie usuwaj komputera z HA. Profil 2.0 i istniejące encje są zachowane.

Aby używać nakładek z HA, włącz **Nakładki → Wiadomości na ekranie** i zapisz ustawienia. Testy lokalne działają również przy wyłączonym udostępnianiu nakładek.

[Pełna instrukcja](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0-alpha.4/docs/V2_QUICKSTART.md)

Wydanie testowe; stabilna wersja pozostaje bez zmian. Instalator nie jest podpisany cyfrowo. Sumy SHA256 są dołączone do paczek.
