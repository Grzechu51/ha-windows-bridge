# HA Windows Bridge 2.0

## Install

1. Download **HA-Windows-Bridge-Setup-2.0.0.exe** from the [latest release](https://github.com/Grzechu51/ha-windows-bridge/releases/latest) and run it from Windows Explorer.
2. In HACS, add `Grzechu51/ha-windows-bridge` as an **Integration**, install version **2.0.0** and restart Home Assistant.
3. Open the Windows app and enter your MQTT connection details in **Settings**. MQTT is needed for volume controls, media and sensors.
4. Enable the features you want to share, apply your changes and start the connection from **Overview**.
5. Add the discovered PC under **Settings → Devices & services** in Home Assistant.

Requirements: Windows 10 or 11 (64-bit), Home Assistant 2026.9.0 or newer, and a broker with the MQTT integration enabled in Home Assistant.

The portable Windows ZIP is an alternative to the installer. Extract the whole folder and keep `_internal` beside the EXE. Run only one copy of Bridge at a time.

## Apps and media

In **Applications**, adjust Windows volume, active app volume and the volume of selected apps. If an app is missing, play some audio in it or add it manually. Enable the apps you want to share with Home Assistant and apply your changes.

Enable the media player feature to share the current Windows media session, including playback controls, track details and artwork. Available controls depend on the player. Pausing playback keeps the current track visible.

## Popups

**Popups are a work in progress.** Their layouts and animations are still being refined.

Enable screen messages in **Notifications**, then use the **HA Windows Bridge: Show Windows overlay** action in Home Assistant to send messages, images or media cards to your PC.

Popups can also use a direct Home Assistant connection:

1. Enter your Home Assistant URL and a long-lived access token in the Windows app. Use the normal server address, without `/api/websocket`.
2. If your PC is already discovered through MQTT, use that same device. For a direct-only setup, add **HA Windows Bridge** in Home Assistant and use the device ID shown in the Windows app.
3. Enable the direct connection, apply your changes and start the connection.

Volume controls, media and sensors still use MQTT. Keep tokens private.

## Settings and updates

Settings are stored in `%LOCALAPPDATA%\HAWindowsBridge\profile-v2.json`. Updates within version 2 preserve this profile. Credentials are protected for your Windows account.

Use **Settings → Export settings** for a settings copy without passwords or tokens. Importing adds settings to the form; apply your changes to use them. Re-enter credentials if you change the connection details.

Before updating, close Bridge from the system tray. Use matching Windows and Home Assistant integration versions, then restart Home Assistant after updating the integration. See the [upgrade guide](RELEASE_GUIDE.md) and [compatibility notes](HOME_ASSISTANT_COMPATIBILITY.md) when moving from an older release.

## Troubleshooting

Check connection status in **Overview** and use **Check connection** or **Reconnect**. Home Assistant restarts are handled automatically once the integration is available again.

For a problem report, export a diagnostic report from **Diagnostics** and describe what happened in a [GitHub issue](https://github.com/Grzechu51/ha-windows-bridge/issues). The diagnostic export excludes passwords and tokens.
