# Home Assistant integration

Connect your Windows PC to Home Assistant with HA Windows Bridge **2.0.0**.

## Install

1. In HACS, add `Grzechu51/ha-windows-bridge` as an **Integration**.
2. Install **HA Windows Bridge 2.0.0** and restart Home Assistant.
3. Install the matching Windows app and enter your MQTT connection details.
4. Enable the features you want to share and add the discovered PC in Home Assistant.

For a manual install, copy `custom_components/ha_windows_bridge` from the **HA-Integration** ZIP into Home Assistant's `config/custom_components/` directory and restart Home Assistant.

You need Home Assistant **2026.9.0 or newer**, a broker and the MQTT integration for volume controls, media and sensors.

## Popups

Enable screen messages in the Windows app, then use **HA Windows Bridge: Show Windows overlay** in a Home Assistant automation to display messages, images and media cards on your PC. Popups can also use a direct Home Assistant connection.

**Popups are still a work in progress.** Layouts and animations are being refined.

## Update

Use matching Windows app and integration versions. Restart Home Assistant after updating the integration. Before upgrading from an older integration, take a backup and check your dashboards and automations: entity IDs can change during migration.

[Setup guide](https://github.com/Grzechu51/ha-windows-bridge/blob/v2.0.0/docs/V2_QUICKSTART.md) · [Downloads](https://github.com/Grzechu51/ha-windows-bridge/releases/latest) · [Report a problem](https://github.com/Grzechu51/ha-windows-bridge/issues)
