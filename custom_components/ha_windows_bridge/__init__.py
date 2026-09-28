from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import camera as camera_component
from homeassistant.components import image as image_component
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import target as target_helpers
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITIES,
    CONF_MEDIA_PLAYER,
    CONF_TRANSPORT,
    DOMAIN,
    SERVICE_CLEAR_OVERLAY,
    SERVICE_REMOVE_OVERLAY,
    SERVICE_SHOW_OVERLAY,
    SERVICE_UPDATE_OVERLAY,
    TRANSPORT_DIRECT,
    direct_overlay_event,
)
from .errors import failed, invalid
from .migration import (
    async_finish_migration,
    async_prepare_migration,
    canonical_direct_entities,
    direct_in_place_journal,
)
from .repairs import (
    clear_migration_conflict,
    clear_migration_issues,
    migration_cleanup_pending,
    migration_conflict,
)
from .runtime import BridgeRuntime
from .websocket import async_register_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_OVERLAY_ID = vol.All(cv.string, vol.Length(min=1, max=64), vol.Match(r"^[A-Za-z0-9_.:-]+$"))
_OVERLAY_COMMON_OPTIONS = {
    vol.Optional("icon"): vol.All(cv.string, vol.Length(max=128)),
    vol.Optional("image"): vol.All(cv.string, vol.Length(max=700 * 1024)),
    vol.Optional("qr"): vol.All(cv.string, vol.Length(max=512)),
    vol.Optional("progress"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional("progress_entity"): cv.entity_id,
    vol.Optional("progress_attribute"): vol.All(cv.string, vol.Length(max=128)),
    vol.Optional("progress_min"): vol.Coerce(float),
    vol.Optional("progress_max"): vol.Coerce(float),
    vol.Optional("duration_entity"): cv.entity_id,
    vol.Optional("duration_attribute"): vol.All(cv.string, vol.Length(max=128)),
    vol.Optional("monitor"): vol.All(vol.Coerce(int), vol.Range(min=0, max=15)),
    vol.Optional("edge_offset"): vol.All(vol.Coerce(int), vol.Range(min=0, max=240)),
    vol.Optional("preset"): vol.In({"default", "success", "warning", "error", "info"}),
    vol.Optional("background_effect"): vol.In({"none", "blur", "liquid"}),
    vol.Optional("media_player_entity"): cv.entity_id,
    vol.Optional("layout"): vol.In(
        {"auto", "compact", "status", "badge", "standard", "media", "camera"}
    ),
    vol.Optional("display_mode"): vol.In({"queue", "parallel"}),
    vol.Optional("priority"): vol.In({"low", "normal", "high", "critical"}),
}
_OVERLAY_SOURCE_OPTIONS = {
    vol.Optional("title_entity"): cv.entity_id,
    vol.Optional("title_attribute"): vol.All(cv.string, vol.Length(max=128)),
    vol.Optional("message_entity"): cv.entity_id,
    vol.Optional("message_attribute"): vol.All(cv.string, vol.Length(max=128)),
    vol.Optional("image_entity"): cv.entity_id,
    vol.Optional("image_url"): vol.All(cv.string, vol.Length(max=700 * 1024)),
}
_OVERLAY_UPDATE_OPTIONS = {
    **_OVERLAY_COMMON_OPTIONS,
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=2, max=60)),
    vol.Optional("pinned"): cv.boolean,
    vol.Optional("show_close_button"): cv.boolean,
    vol.Optional("close_on_click"): cv.boolean,
    vol.Optional("pause_on_hover"): cv.boolean,
    vol.Optional("show_lifetime"): cv.boolean,
    vol.Optional("media"): cv.boolean,
    vol.Optional("corner"): vol.In(
        {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
    ),
    vol.Optional("size_mode"): vol.In({"auto", "manual"}),
    vol.Optional("width"): vol.All(vol.Coerce(int), vol.Range(min=240, max=1200)),
    vol.Optional("height"): vol.All(vol.Coerce(int), vol.Range(min=90, max=900)),
    vol.Optional("opacity"): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
}
_SHOW_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Optional("message"): vol.All(cv.string, vol.Length(max=2048)),
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("notification_id"): _OVERLAY_ID,
        **_OVERLAY_COMMON_OPTIONS,
        **_OVERLAY_SOURCE_OPTIONS,
        vol.Optional("media"): cv.boolean,
        vol.Required("opacity", default=0.94): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Required("size_mode", default="auto"): vol.In({"auto", "manual"}),
        vol.Required("width", default=400): vol.All(
            vol.Coerce(int), vol.Range(min=240, max=1200)
        ),
        vol.Required("height", default=160): vol.All(
            vol.Coerce(int), vol.Range(min=90, max=900)
        ),
        vol.Required("duration", default=8): vol.All(
            vol.Coerce(int), vol.Range(min=2, max=60)
        ),
        vol.Optional("pinned"): cv.boolean,
        vol.Optional("show_close_button"): cv.boolean,
        vol.Optional("close_on_click"): cv.boolean,
        vol.Optional("pause_on_hover"): cv.boolean,
        vol.Optional("show_lifetime"): cv.boolean,
        vol.Required("corner", default="top_right"): vol.In(
            {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
        ),
    }
)
_UPDATE_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("notification_id"): _OVERLAY_ID,
        vol.Optional("message"): vol.All(cv.string, vol.Length(max=2048)),
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=128)),
        **_OVERLAY_UPDATE_OPTIONS,
        **_OVERLAY_SOURCE_OPTIONS,
    }
)
_REMOVE_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("notification_id"): _OVERLAY_ID}
)
_CLEAR_OVERLAY_SCHEMA = cv.make_entity_service_schema({})
_MAX_MEDIA_IMAGE_BYTES = 512 * 1024
_MEDIA_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _image_data_uri(content_type: str, content: bytes) -> str:
    """Encode a supported, bounded image for the Windows overlay payload."""
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if (
        normalized_type not in _MEDIA_IMAGE_TYPES
        or not content
        or len(content) > _MAX_MEDIA_IMAGE_BYTES
    ):
        return ""
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{normalized_type};base64,{encoded}"


def _text_attribute(value: Any) -> str:
    """Return a readable media attribute."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _number_attribute(value: Any) -> float:
    """Return a non-negative media number."""
    try:
        numeric = float(value)
        return max(0.0, numeric) if math.isfinite(numeric) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _live_media_position(state_value: str, attributes: dict[str, Any]) -> float:
    """Calculate the current position from Home Assistant media attributes."""
    position = _number_attribute(attributes.get("media_position"))
    duration = _number_attribute(attributes.get("media_duration"))
    updated_at = attributes.get("media_position_updated_at")
    if state_value == "playing" and updated_at:
        try:
            if isinstance(updated_at, datetime):
                updated = updated_at
            else:
                updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            position += max(0.0, (datetime.now(UTC) - updated).total_seconds())
        except (TypeError, ValueError):
            pass
    return min(duration, position) if duration > 0 else position


async def _async_media_image(hass: HomeAssistant, picture: str) -> str:
    """Fetch a signed Home Assistant entity picture for the Windows client."""
    picture = picture.strip()
    if picture.startswith("data:image/"):
        return picture if len(picture.encode("utf-8")) <= 700 * 1024 else ""
    try:
        if picture.startswith("/"):
            picture = urljoin(
                f"{get_url(hass, prefer_external=False).rstrip('/')}/",
                picture.lstrip("/"),
            )
        if not picture.startswith(("http://", "https://")):
            return ""
        async with asyncio.timeout(8):
            async with async_get_clientsession(hass).get(picture) as response:
                if response.status >= 400:
                    return ""
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type not in _MEDIA_IMAGE_TYPES:
                    return ""
                image = await response.content.read(_MAX_MEDIA_IMAGE_BYTES + 1)
    except Exception:  # Network and proxy errors should not block the notification.
        return ""
    return _image_data_uri(content_type, image)


async def _async_entity_image(hass: HomeAssistant, entity_id: str) -> str:
    """Read the current frame from a camera or Home Assistant image entity."""
    try:
        if entity_id.startswith("camera."):
            source = await camera_component.async_get_image(
                hass, entity_id, width=1280, height=720
            )
        elif entity_id.startswith("image."):
            source = await image_component.async_get_image(hass, entity_id)
        else:
            return ""
    except (HomeAssistantError, TimeoutError, ValueError):
        return ""
    return _image_data_uri(source.content_type, source.content)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register validated actions shared by all configured Windows bridges."""
    async_register_commands(hass)

    async def publish_overlay(call: ServiceCall) -> None:
        action = {
            SERVICE_SHOW_OVERLAY: "show",
            SERVICE_UPDATE_OVERLAY: "update",
            SERVICE_REMOVE_OVERLAY: "remove",
            SERVICE_CLEAR_OVERLAY: "clear",
        }[call.service]
        registry = er.async_get(hass)
        selected = target_helpers.TargetSelection(call.data)
        referenced = target_helpers.async_extract_referenced_entity_ids(
            hass, selected, expand_group=True
        )
        entity_ids = referenced.referenced | referenced.indirectly_referenced
        runtimes = {}
        for entity_id in entity_ids:
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(entity_id, POLICY_CONTROL):
                    raise failed("not_authorized_control", "Not authorized to control this overlay entity")
            registered = registry.async_get(entity_id)
            if registered is None or registered.config_entry_id is None:
                continue
            entry = hass.config_entries.async_get_entry(registered.config_entry_id)
            runtime = getattr(entry, "runtime_data", None)
            if (runtime is None or registered.domain != Platform.NOTIFY.value
                    or registered.platform != DOMAIN or registered.disabled_by is not None
                    or registered.unique_id != runtime.overlay_unique_id):
                continue
            runtimes[registered.config_entry_id] = runtime
        if not runtimes:
            raise invalid("popup_required", "Select an enabled HA Windows Bridge popup entity")

        for field in ("progress_min", "progress_max", "opacity"):
            if field in call.data and not math.isfinite(float(call.data[field])):
                raise invalid("number_must_be_finite", f"{field} must be finite", field=field)

        options: dict[str, Any] = {
            key: value
            for key, value in call.data.items()
            if key not in {"entity_id", "device_id", "area_id", "floor_id", "label_id"}
            and key
            not in {
                "title",
                "message",
                "notification_id",
                "title_entity",
                "title_attribute",
                "message_entity",
                "message_attribute",
            }
        }
        for value_field, entity_field, attribute_field, minimum, maximum in (
            ("progress", "progress_entity", "progress_attribute", 0, 100),
            ("duration", "duration_entity", "duration_attribute", 2, 60),
        ):
            entity_id = str(call.data.get(entity_field, "")).strip()
            if not entity_id:
                continue
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(entity_id, POLICY_READ):
                    raise failed("not_authorized_read_source", f"Not authorized to read the source entity: {entity_id}")
            state = hass.states.get(entity_id)
            if state is None:
                raise invalid("source_unavailable", f"Source entity is unavailable: {entity_id}")
            attribute = str(call.data.get(attribute_field, "")).strip()
            raw_value = state.attributes.get(attribute) if attribute else state.state
            try:
                numeric = float(raw_value)
                if not math.isfinite(numeric):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise invalid("source_not_numeric",
                    f"Source entity does not contain a numeric value: {entity_id}"
                ) from None
            if value_field == "progress":
                source_min = float(call.data.get("progress_min", 0))
                source_max = float(call.data.get("progress_max", 100))
                span = source_max - source_min
                if span <= 0 or not math.isfinite(span):
                    raise invalid(
                        "progress_range_invalid",
                        "Progress maximum must be greater than progress minimum",
                    )
                scaled = (numeric - source_min) / span * 100
                if not math.isfinite(scaled):
                    raise invalid("progress_range_invalid", "Progress range cannot be normalized")
                numeric = round(scaled)
            else:
                numeric = round(numeric)
            options[value_field] = max(minimum, min(maximum, numeric))
        for helper_field in (
            "progress_entity",
            "progress_attribute",
            "progress_min",
            "progress_max",
            "duration_entity",
            "duration_attribute",
        ):
            options.pop(helper_field, None)

        async def text_from_entity(entity_field: str, attribute_field: str) -> str:
            entity_id = str(call.data.get(entity_field, "")).strip()
            if not entity_id:
                return ""
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(
                    entity_id, POLICY_READ
                ):
                    raise failed("not_authorized_read_source",
                        f"Not authorized to read the source entity: {entity_id}"
                    )
            state = hass.states.get(entity_id)
            if state is None:
                raise invalid("source_unavailable", f"Source entity is unavailable: {entity_id}")
            attribute = str(call.data.get(attribute_field, "")).strip()
            value = state.attributes.get(attribute) if attribute else state.state
            return _text_attribute(value)

        entity_title = await text_from_entity("title_entity", "title_attribute")
        entity_message = await text_from_entity("message_entity", "message_attribute")
        image_entity = str(options.pop("image_entity", "")).strip()
        image_url = str(options.pop("image_url", "")).strip()
        if image_entity:
            if not image_entity.startswith(("camera.", "image.")):
                raise invalid("camera_or_image_required", "Select a camera or image entity")
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(
                    image_entity, POLICY_READ
                ):
                    raise failed("not_authorized_image",
                        "Not authorized to read the selected image entity"
                    )
            entity_image = await _async_entity_image(hass, image_entity)
            if not entity_image:
                raise invalid("image_entity_unsupported",
                    "The selected camera or image entity did not return a supported image"
                )
            options["image"] = entity_image
        elif image_url:
            url_image = await _async_media_image(hass, image_url)
            if not url_image:
                raise invalid("image_url_unsupported",
                    "The image URL did not return a supported image"
                )
            options["image"] = url_image
        media_player_entity = str(options.pop("media_player_entity", "")).strip()
        media_title = ""
        media_message = ""
        if media_player_entity and action in {"show", "update"}:
            if not media_player_entity.startswith("media_player."):
                raise invalid("media_player_required", "Select a media_player entity")
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(
                    media_player_entity, POLICY_READ
                ):
                    raise failed("not_authorized_media_player",
                        "Not authorized to read the selected media player"
                    )
            media_state = hass.states.get(media_player_entity)
            if media_state is None:
                raise invalid("media_player_unavailable",
                    f"Selected media player is unavailable: {media_player_entity}"
                )
            attributes = media_state.attributes
            media_source = _text_attribute(attributes.get("friendly_name")) or (
                media_player_entity.rsplit(".", 1)[-1].replace("_", " ").title()
            )
            media_title = _text_attribute(attributes.get("media_title")) or media_state.state.replace(
                "_", " "
            ).capitalize()
            media_message_parts = [
                _text_attribute(attributes.get("media_artist")),
                _text_attribute(attributes.get("media_album_name")),
            ]
            media_message = " · ".join(
                dict.fromkeys(part for part in media_message_parts if part)
            )
            if not media_message and not attributes.get("media_title"):
                media_message = media_state.state.replace("_", " ").capitalize()
            duration = _number_attribute(attributes.get("media_duration"))
            options.update(
                {
                    "media": False,
                    "layout": "media",
                    "media_source": media_source,
                    "media_position": _live_media_position(media_state.state, attributes),
                    "media_duration": duration,
                    "media_playing": media_state.state == "playing",
                }
            )
            icon = _text_attribute(attributes.get("icon"))
            options.setdefault("icon", icon if icon.startswith("mdi:") else "mdi:cast-audio")
            picture = _text_attribute(attributes.get("entity_picture"))
            if picture and (image := await _async_media_image(hass, picture)):
                options["image"] = image
        options["action"] = action
        if notification_id := call.data.get("notification_id"):
            options["id"] = notification_id
        title = str(call.data.get("title", "")).strip() or entity_title or media_title
        message = (
            str(call.data.get("message", "")).strip()
            or entity_message
            or media_message
        )
        badge_has_content = options.get("layout") == "badge" and bool(
            options.get("icon")
            or options.get("image")
            or options.get("progress") is not None
        )
        if (
            action == "show"
            and not message
            and not title
            and not options.get("media")
            and not options.get("image")
            and not options.get("qr")
            and not badge_has_content
        ):
            raise invalid("content_required",
                "Provide content, select a Home Assistant media player, "
                "or enable current Windows media"
            )
        default_title = "" if options.get("layout") == "badge" else "Home Assistant"
        payload_title = title or (default_title if action == "show" else "")
        content = {"data": options}
        # An update is a patch: absent text must not erase existing content.
        if action != "update" or "title" in call.data or title:
            content["title"] = payload_title
        if action != "update" or "message" in call.data or message:
            content["message"] = message
        payload = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 768 * 1024:
            raise invalid("payload_too_large", "Overlay payload is too large")
        results = await asyncio.gather(*(
            runtime.send(runtime.overlay_topic, payload, direct=bool(runtime.overlay_event_type))
            for runtime in runtimes.values()
        ), return_exceptions=True)
        failed_count = sum(isinstance(result, Exception) for result in results)
        if failed_count:
            raise failed(
                "targets_unconfirmed",
                f"{failed_count} Windows Bridge target(s) did not confirm the command",
                count=str(failed_count),
            )

    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_OVERLAY, publish_overlay, schema=_SHOW_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_OVERLAY, publish_overlay, schema=_UPDATE_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_OVERLAY, publish_overlay, schema=_REMOVE_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_OVERLAY, publish_overlay, schema=_CLEAR_OVERLAY_SCHEMA
    )
    return True


def _entry_platforms(hass: HomeAssistant, entry: ConfigEntry) -> list:
    """Return only entity platforms created for this config entry."""
    return [
        platform for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if platform.config_entry is entry
    ]


def _forwarded_entities_ready(hass: HomeAssistant, entry: ConfigEntry, platforms: list) -> bool:
    """Detect entity-add errors that HA logs without failing platform setup."""
    by_domain = {platform.domain: platform for platform in platforms}
    if any(
        platform not in by_domain or not by_domain[platform]._setup_complete
        for platform in PLATFORMS
    ):
        return False
    expected = [
        (definition["platform"], str(definition["unique_id"]))
        for definition in entry.data.get(CONF_ENTITIES, [])
        if isinstance(definition, dict) and definition.get("unique_id")
    ]
    if entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled", False):
        expected.append((Platform.MEDIA_PLAYER, f"{entry.data[CONF_DEVICE_ID]}_media_player"))
    registry = er.async_get(hass)
    for domain, unique_id in expected:
        platform = by_domain.get(domain)
        if platform is None:
            return False
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        registered = registry.async_get(entity_id) if entity_id else None
        if registered is None or registered.config_entry_id != entry.entry_id:
            return False
        if registered.disabled_by is None and entity_id not in platform.entities:
            return False
    return True


async def _async_rollback_platforms(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload only instantiated platforms, then release their HA registrations."""
    platforms = _entry_platforms(hass, entry)
    if not platforms:
        return True
    domains = list(dict.fromkeys(platform.domain for platform in platforms))
    try:
        if not await hass.config_entries.async_unload_platforms(entry, domains):
            return False
        for platform in platforms:
            if platform in entity_platform.async_get_platforms(hass, DOMAIN):
                await platform.async_destroy()
    except Exception:
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up every entity announced by one Windows bridge."""
    direct = entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT
    if not direct and not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady(
            "Configure and enable the Home Assistant MQTT integration first",
            translation_domain=DOMAIN, translation_key="mqtt_required",
        )

    try:
        await async_prepare_migration(hass, entry)
    except Exception as exc:
        migration_conflict(hass, entry)
        raise ConfigEntryNotReady(
            "Windows Bridge migration needs manual review",
            translation_domain=DOMAIN, translation_key="migration_conflict",
        ) from exc
    clear_migration_conflict(hass, entry)

    overlay_definition = next(
        (
            definition
            for definition in entry.data.get(CONF_ENTITIES, [])
            if isinstance(definition, dict)
            and definition.get("platform") == Platform.NOTIFY.value
            and (
                str(definition.get("command_topic", "")).endswith("/overlay/show/set")
                or str(definition.get("command_topic", "")).startswith("direct://")
            )
        ),
        {},
    )
    popup_direct = str(overlay_definition.get("command_topic", "")).startswith("direct://")
    overlay_topic = "" if popup_direct else str(overlay_definition.get("command_topic", ""))
    runtime = BridgeRuntime(
        hass=hass, device_id=str(entry.data[CONF_DEVICE_ID]),
        overlay_unique_id=str(overlay_definition.get("unique_id", "")), overlay_topic=overlay_topic,
        overlay_event_type=direct_overlay_event(str(entry.data[CONF_DEVICE_ID])) if popup_direct else "",
        protocol=entry.data.get("protocol", {}),
    )
    entry.runtime_data = runtime
    try:
        await runtime.start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if runtime.setup_failed or not _forwarded_entities_ready(
            hass, entry, _entry_platforms(hass, entry)
        ):
            raise ConfigEntryNotReady(
                "Windows Bridge entity setup did not complete",
                translation_domain=DOMAIN, translation_key="entity_setup_failed",
            )
    except BaseException:
        # HA can log platform and entity-add failures without propagating them.
        unloaded = await _async_rollback_platforms(hass, entry)
        await runtime.async_close()
        if unloaded:
            entry.runtime_data = None
        raise
    entry.async_on_unload(runtime.close)
    # Cleanup starts only after HA has loaded and verified the canonical model.
    # A cleanup error leaves the working bridge online and its journal for replay.
    try:
        await async_finish_migration(hass, entry)
    except Exception:
        runtime.migration_incomplete = True
        migration_cleanup_pending(hass, entry)
        _LOGGER.exception("Windows Bridge identity cleanup is pending retry")
    else:
        clear_migration_issues(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA Windows Bridge."""
    platforms = _entry_platforms(hass, entry)
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, list(dict.fromkeys(platform.domain for platform in platforms))
    ) if platforms else True
    if unload_ok:
        for platform in platforms:
            if platform in entity_platform.async_get_platforms(hass, DOMAIN):
                await platform.async_destroy()
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None:
            await runtime.async_close()
            entry.runtime_data = None
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Upgrade v1 entries; an existing MQTT owner always wins a duplicate pair."""
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True
    device_id = str(entry.data[CONF_DEVICE_ID])
    if entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT and not any(
        other.unique_id == device_id for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        journal = direct_in_place_journal(hass, entry)
        hass.config_entries.async_update_entry(
            entry, version=2, unique_id=device_id,
            data={**entry.data, CONF_ENTITIES: canonical_direct_entities(device_id),
                  "migration_journal": journal, "direct_popup_enabled": True})
    else:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove any migration Repair when this entry is deleted."""
    clear_migration_issues(hass, entry)
