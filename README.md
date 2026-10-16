<p align="center">
  <img src="https://raw.githubusercontent.com/Grzechu51/ha-windows-bridge/main/assets/icon.png" alt="HA Windows Bridge" width="128">
</p>

<h1 align="center">HA Windows Bridge</h1>

<p align="center">Bring your Windows PC into Home Assistant.</p>

Control volume, manage playback and check your PC from Home Assistant. Choose which features to share and keep everything in one place.

> **Popups are still a work in progress.** Their appearance and behaviour may change.

## Features

- Windows volume and separate volume controls for selected apps.
- Media playback controls, track details and album artwork.
- Active app, idle time and PC lock status.
- CPU, RAM, GPU, disks, battery and Windows Update information.
- Desktop notifications and popups from Home Assistant.
- Optional PC lock, sleep, restart and shutdown controls.

## Get started

You need **Windows 10 or 11 (64-bit)** and **Home Assistant 2026.9.0 or newer**. Volume controls, media and sensors require MQTT.

1. Download the Windows installer from the [latest release](https://github.com/Grzechu51/ha-windows-bridge/releases/latest).
2. Add this repository to HACS as an **Integration**, install the version matching the Windows app and restart Home Assistant.
3. Open the Windows app, enter your connection details and enable the features you want to use.
4. Apply your settings, start the connection and add the discovered PC in Home Assistant.

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Grzechu51&repository=ha-windows-bridge&category=integration)

For a manual integration install, download the **HA-Integration** ZIP from the same release, copy its `ha_windows_bridge` folder into Home Assistant's `config/custom_components/` folder and restart Home Assistant. The release also includes a portable Windows ZIP; extract the whole folder before running it.

## Popups

Send messages, images and media cards to your Windows desktop using the **HA Windows Bridge: Show Windows overlay** action in Home Assistant. Popups can use MQTT or a direct Home Assistant connection.

**This feature is under active development.** Layouts and animations are still being refined.

## Help

- [Setup and settings guide](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0-alpha.12/docs/V2_QUICKSTART.md) (Polish)
- [Upgrade and compatibility notes](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0-alpha.12/docs/HOME_ASSISTANT_COMPATIBILITY.md)
- [Report a problem](https://github.com/Grzechu51/ha-windows-bridge/issues)

Before upgrading from an older integration, back up Home Assistant and check the compatibility notes.

## License

[GNU AGPL v3](LICENSE)
