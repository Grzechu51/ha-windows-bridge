# Home Assistant compatibility

HA Windows Bridge 2.0 requires **Home Assistant 2026.9.0 or newer**. The integration is tested against Home Assistant 2026.9.0 and 2026.9.3.

Install the Windows app and Home Assistant integration from the same release. Sensors, volume controls and media use MQTT. Popups support MQTT and a direct Home Assistant connection.

## Upgrading from an older integration

Back up Home Assistant before upgrading. Version 2 consolidates the MQTT and direct connections into one PC device. Existing entity IDs can change, so check dashboards and automations after the update. History attached to old entities may not carry over.

Use the device ID already stored in your Windows profile. If the PC is discovered through MQTT, you do not need to add a second device for the direct connection.

Check any repair notifications in Home Assistant after migration. If setup fails, keep your backup and report the problem before deleting or recreating devices.

## Updating Windows

Updates within version 2 keep the existing Windows profile and connection settings. Version 0.x settings are not imported automatically; keep the old configuration backup and configure version 2 explicitly.

See the [setup guide](V2_QUICKSTART.md) and [update and recovery guide](RELEASE_GUIDE.md) for the installation steps.
