# Installation, updates and recovery

Download the Windows app and matching Home Assistant integration from the [latest release](https://github.com/Grzechu51/ha-windows-bridge/releases/latest). The current version is **2.0.0**.

## Choose a download

- **Setup.exe** installs the Windows app for your account.
- **win64.zip** is the portable Windows app. Extract the complete folder.
- **HA-Integration.zip** is for manual Home Assistant integration installation. Copy `custom_components/ha_windows_bridge` into Home Assistant's `config/custom_components/` directory, then restart Home Assistant. HACS is the recommended alternative.
- **SHA256SUMS.txt** contains checksums for the downloads.

The Windows installer uses `%LOCALAPPDATA%\Programs\HA Windows Bridge` by default. Start the app from its installed shortcut. See the [setup guide](V2_QUICKSTART.md) for connection and feature settings.

## Update

1. Exit Bridge from the Windows system tray.
2. Back up `%LOCALAPPDATA%\HAWindowsBridge` and take a Home Assistant backup.
3. Install the new Windows version, or extract the portable ZIP into a separate folder.
4. Update the matching Home Assistant integration through HACS or the integration ZIP, then restart Home Assistant.
5. Open Bridge and check your connection and enabled features.

Version 2 updates preserve `profile-v2.json`. A settings export excludes credentials and is not a complete backup of the profile. Credentials are tied to your Windows account.

When upgrading from version 0.x, keep your old configuration backup and configure version 2 explicitly. Home Assistant entity IDs may change during the migration; check dashboards and automations. See the [compatibility notes](HOME_ASSISTANT_COMPATIBILITY.md).

## Recover a connection

Check the server address, credentials and displayed connection status. Use **Check connection** or **Reconnect** after correcting settings. Bridge reconnects automatically after temporary connection loss and Home Assistant restarts. An invalid token or missing permissions needs to be corrected in the settings.

If a Windows update fails, exit Bridge and reinstall the complete app. Keep the profile backup private. Avoid mixing files from different versions.

## Uninstall

Exit Bridge from the tray, then uninstall it through Windows **Installed apps**. For a portable copy, remove its extracted folder after closing the app.

The settings folder is separate from the application. Keep it if you plan to reinstall. Remove it yourself only when you no longer need the saved settings. Remove the integration in Home Assistant if you no longer use Bridge.

## Build from source

For maintainers on Windows with Python and Inno Setup installed:

```powershell
.\build.ps1 -Installer
```

The build runs tests, creates the Windows package and installer, checks startup and generates checksums in `dist`. Without a configured signing certificate, binaries are unsigned.

**Popups remain a work in progress.** Their layouts and animations may change independently of other features.
