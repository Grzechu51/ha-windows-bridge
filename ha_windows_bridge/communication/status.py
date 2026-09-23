"""User-facing connection status shared by the window and diagnostics."""

from ..i18n import active_language, translate

CONNECTION_NAMES = {"mqtt": "MQTT", "home_assistant": "Home Assistant"}
CONNECTION_STATES = {
    "stopped": "Zatrzymane", "connecting": "Łączenie…", "connected": "Połączono",
    "retry_wait": "Ponawianie połączenia", "suspended": "Wstrzymane",
    "auth_error": "Odmowa dostępu", "configuration_error": "Sprawdź konfigurację",
}
CONNECTION_ERRORS = {
    "authentication": "Nieprawidłowy lub unieważniony token / dane logowania",
    "unauthorized": "Brak uprawnień do sterowania popupem tego komputera",
    "integration_missing": "Zaktualizuj integrację HA Windows Bridge i uruchom HA ponownie",
    "bridge_not_configured": "Dodaj ten komputer w integracji HA Windows Bridge",
    "popup_unavailable": "Włącz encję popupu tego komputera w Home Assistant",
    "bridge_not_ready": "Integracja HA jeszcze się uruchamia",
    "bridge_busy": "Inna instancja aplikacji jest już połączona",
    "session_expired": "Sesja wygasła — łączenie ponownie",
    "protocol_mismatch": "Zaktualizuj aplikację i integrację do tej samej wersji",
    "server_error": "Błąd integracji — sprawdź dziennik Home Assistant",
    "network": "Serwer jest nieosiągalny lub połączenie zostało przerwane",
    "disconnected": "Połączenie zostało przerwane",
}


def connection_text(status):
    language = active_language()
    text = translate(CONNECTION_STATES.get(status.state, str(status.state)), language)
    if status.error:
        text += " — " + translate(CONNECTION_ERRORS.get(status.error, "Błąd połączenia"), language)
    return text
