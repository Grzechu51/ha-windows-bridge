from __future__ import annotations

import asyncio
import base64
import json
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
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import target as target_helpers
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
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
    SERVICE_SHOW_SAVED_OVERLAY,
    SERVICE_UPDATE_OVERLAY,
    TRANSPORT_DIRECT,
    direct_overlay_event,
    direct_template_catalog_event,
    direct_template_command_event,
    template_dispatcher_signal,
)

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
_TEMPLATE_ID = vol.All(
    cv.string, vol.Length(min=1, max=64), vol.Match(r"^[a-z0-9_]+$")
)
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
    # Kept for existing YAML automations; the visual editor now uses size_mode.
    vol.Optional("size"): vol.In({"small", "medium", "large"}),
    vol.Optional("preset"): vol.In({"default", "success", "warning", "error", "info"}),
    vol.Optional("background_effect"): vol.In({"none", "blur", "liquid"}),
    # Backward compatibility for automations created before background_effect.
    vol.Optional("glass"): cv.boolean,
    vol.Optional("media_player_entity"): cv.entity_id,
    vol.Optional("layout"): vol.In(
        {"auto", "compact", "status", "badge", "standard", "media", "camera"}
    ),
    vol.Optional("display_mode"): vol.In({"queue", "parallel"}),
    vol.Optional("channel"): vol.In({"general", "security", "system", "media", "work"}),
    vol.Optional("priority"): vol.In({"low", "normal", "high", "critical"}),
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
    }
)
_REMOVE_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("notification_id"): _OVERLAY_ID}
)
_CLEAR_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional("channel"): vol.In({"general", "security", "system", "media", "work"})}
)
_SHOW_SAVED_OVERLAY_SCHEMA = vol.Schema(
    {
        vol.Required("template_entity"): cv.entity_id,
        vol.Optional("template_id"): _TEMPLATE_ID,
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("message"): vol.All(cv.string, vol.Length(max=2048)),
        vol.Optional("notification_id"): _OVERLAY_ID,
        vol.Optional("title_entity"): cv.entity_id,
        vol.Optional("title_attribute"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("message_entity"): cv.entity_id,
        vol.Optional("message_attribute"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("image_entity"): cv.entity_id,
        vol.Optional("image_url"): vol.All(cv.string, vol.Length(max=700 * 1024)),
        vol.Optional("progress_entity"): cv.entity_id,
        vol.Optional("progress_attribute"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("progress_min", default=0): vol.Coerce(float),
        vol.Optional("progress_max", default=100): vol.Coerce(float),
        vol.Optional("duration_entity"): cv.entity_id,
        vol.Optional("duration_attribute"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("media_player_entity"): cv.entity_id,
    }
)
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


def _normalize_template_catalog(raw: Any, device_id: str) -> tuple[list[dict[str, str]], str]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return [], ""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [], ""
    if not isinstance(raw, dict) or str(raw.get("device_id", "")) != device_id:
        return [], ""
    templates: list[dict[str, str]] = []
    names: set[str] = set()
    identifiers: set[str] = set()
    for item in raw.get("templates", [])[:64]:
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()[:64]
        if (
            not template_id
            or len(template_id) > 64
            or not template_id.replace("_", "").isalnum()
            or template_id in identifiers
            or not name
            or name.casefold() in names
        ):
            continue
        identifiers.add(template_id)
        names.add(name.casefold())
        templates.append({"id": template_id, "name": name})
    selected = str(raw.get("selected", "")).strip()
    if selected not in identifiers:
        selected = templates[0]["id"] if templates else ""
    return templates, selected


def _text_attribute(value: Any) -> str:
    """Return a readable media attribute."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _number_attribute(value: Any) -> float:
    """Return a non-negative media number."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
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

    async def publish_overlay(call: ServiceCall) -> None:
        action = {
            SERVICE_SHOW_OVERLAY: "show",
            SERVICE_SHOW_SAVED_OVERLAY: "show",
            SERVICE_UPDATE_OVERLAY: "update",
            SERVICE_REMOVE_OVERLAY: "remove",
            SERVICE_CLEAR_OVERLAY: "clear",
        }[call.service]
        registry = er.async_get(hass)
        saved_template_action = call.service == SERVICE_SHOW_SAVED_OVERLAY
        if saved_template_action:
            entity_ids = {str(call.data["template_entity"])}
        else:
            selected = target_helpers.TargetSelection(call.data)
            referenced = target_helpers.async_extract_referenced_entity_ids(
                hass, selected, expand_group=True
            )
            entity_ids = referenced.referenced | referenced.indirectly_referenced
        topics: set[str] = set()
        event_types: set[str] = set()
        selected_template_id = ""
        for entity_id in entity_ids:
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(entity_id, POLICY_CONTROL):
                    raise HomeAssistantError("Not authorized to control this overlay entity")
            registered = registry.async_get(entity_id)
            if registered is None or registered.config_entry_id is None:
                continue
            runtime = hass.data.get(DOMAIN, {}).get(registered.config_entry_id, {})
            expected_unique_id = (
                runtime.get("template_select_unique_id")
                if saved_template_action
                else runtime.get("overlay_unique_id")
            )
            if registered.unique_id != expected_unique_id:
                continue
            if saved_template_action:
                selected_template_id = str(
                    call.data.get("template_id")
                    or runtime.get("selected_template_id", "")
                ).strip()
            if topic := runtime.get("overlay_topic"):
                topics.add(str(topic))
            if event_type := runtime.get("overlay_event_type"):
                event_types.add(str(event_type))
        if not topics and not event_types:
            raise HomeAssistantError("Select an enabled HA Windows Bridge popup entity")
        if saved_template_action and not selected_template_id:
            raise HomeAssistantError(
                "The selected computer has not synchronized any saved popup yet"
            )

        options: dict[str, Any] = {
            key: value
            for key, value in call.data.items()
            if key not in {"entity_id", "device_id", "area_id", "floor_id", "label_id"}
            and key
            not in {
                "title",
                "message",
                "notification_id",
                "template_entity",
                "template_id",
                "title_entity",
                "title_attribute",
                "message_entity",
                "message_attribute",
            }
        }
        if saved_template_action:
            options["template_id"] = selected_template_id
        for value_field, entity_field, attribute_field, minimum, maximum in (
            ("progress", "progress_entity", "progress_attribute", 0, 100),
            ("duration", "duration_entity", "duration_attribute", 2, 60),
        ):
            entity_id = str(call.data.get(entity_field, "")).strip()
            if not entity_id:
                continue
            state = hass.states.get(entity_id)
            if state is None:
                raise HomeAssistantError(f"Source entity is unavailable: {entity_id}")
            attribute = str(call.data.get(attribute_field, "")).strip()
            raw_value = state.attributes.get(attribute) if attribute else state.state
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                raise HomeAssistantError(
                    f"Source entity does not contain a numeric value: {entity_id}"
                ) from None
            if value_field == "progress":
                source_min = float(call.data.get("progress_min", 0))
                source_max = float(call.data.get("progress_max", 100))
                if source_max <= source_min:
                    raise HomeAssistantError(
                        "Progress maximum must be greater than progress minimum"
                    )
                numeric = round((numeric - source_min) / (source_max - source_min) * 100)
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
                    raise HomeAssistantError(
                        f"Not authorized to read the source entity: {entity_id}"
                    )
            state = hass.states.get(entity_id)
            if state is None:
                raise HomeAssistantError(f"Source entity is unavailable: {entity_id}")
            attribute = str(call.data.get(attribute_field, "")).strip()
            value = state.attributes.get(attribute) if attribute else state.state
            return _text_attribute(value)

        entity_title = await text_from_entity("title_entity", "title_attribute")
        entity_message = await text_from_entity("message_entity", "message_attribute")
        image_entity = str(options.pop("image_entity", "")).strip()
        image_url = str(options.pop("image_url", "")).strip()
        if image_entity:
            if not image_entity.startswith(("camera.", "image.")):
                raise HomeAssistantError("Select a camera or image entity")
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(
                    image_entity, POLICY_READ
                ):
                    raise HomeAssistantError(
                        "Not authorized to read the selected image entity"
                    )
            entity_image = await _async_entity_image(hass, image_entity)
            if not entity_image:
                raise HomeAssistantError(
                    "The selected camera or image entity did not return a supported image"
                )
            options["image"] = entity_image
        elif image_url:
            url_image = await _async_media_image(hass, image_url)
            if not url_image:
                raise HomeAssistantError(
                    "The image URL did not return a supported image"
                )
            options["image"] = url_image
        media_player_entity = str(options.pop("media_player_entity", "")).strip()
        media_title = ""
        media_message = ""
        if media_player_entity and action in {"show", "update"}:
            if not media_player_entity.startswith("media_player."):
                raise HomeAssistantError("Select a media_player entity")
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(
                    media_player_entity, POLICY_READ
                ):
                    raise HomeAssistantError(
                        "Not authorized to read the selected media player"
                    )
            media_state = hass.states.get(media_player_entity)
            if media_state is None:
                raise HomeAssistantError(
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
            and not badge_has_content
            and not options.get("template_id")
        ):
            raise HomeAssistantError(
                "Provide content, select a Home Assistant media player, "
                "or enable current Windows media"
            )
        default_title = "" if options.get("layout") == "badge" else "Home Assistant"
        payload_title = title or (default_title if action == "show" else "")
        payload = json.dumps(
            {
                "title": payload_title,
                "message": message,
                "data": options,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > 768 * 1024:
            raise HomeAssistantError("Overlay payload is too large")
        for topic in topics:
            await mqtt.async_publish(hass, topic, payload, qos=1, retain=False)
        event_data = {"title": payload_title, "message": message, "data": options}
        for event_type in event_types:
            hass.bus.async_fire(event_type, event_data, context=call.context)

    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_OVERLAY, publish_overlay, schema=_SHOW_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_SAVED_OVERLAY,
        publish_overlay,
        schema=_SHOW_SAVED_OVERLAY_SCHEMA,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up every entity announced by one Windows bridge."""
    direct = entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT
    if not direct and not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("Configure and enable the Home Assistant MQTT integration first")

    valid_unique_ids = {
        str(definition["unique_id"])
        for definition in entry.data.get(CONF_ENTITIES, [])
        if isinstance(definition, dict) and definition.get("unique_id")
    }
    if entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled", False):
        valid_unique_ids.add(f"{entry.data[CONF_DEVICE_ID]}_media_player")
    valid_unique_ids.add(f"{entry.data[CONF_DEVICE_ID]}_overlay_template")

    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id not in valid_unique_ids:
            registry.async_remove(registered.entity_id)

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
    overlay_topic = "" if direct else str(overlay_definition.get("command_topic", ""))
    template_root = (
        f"{overlay_topic.removesuffix('/show/set')}/templates" if overlay_topic else ""
    )
    runtime: dict[str, Any] = {
        "unique_ids": valid_unique_ids,
        "overlay_unique_id": overlay_definition.get("unique_id", ""),
        "template_select_unique_id": f"{entry.data[CONF_DEVICE_ID]}_overlay_template",
        "overlay_topic": overlay_topic,
        "overlay_event_type": (
            direct_overlay_event(str(entry.data[CONF_DEVICE_ID])) if direct else ""
        ),
        "template_command_topic": f"{template_root}/set" if template_root else "",
        "template_state_topic": f"{template_root}/state" if template_root else "",
        "template_catalog": [],
        "selected_template_id": "",
        "unsubscribers": [],
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    @callback
    def apply_template_catalog(raw: Any) -> None:
        templates, selected = _normalize_template_catalog(
            raw, str(entry.data[CONF_DEVICE_ID])
        )
        runtime["template_catalog"] = templates
        runtime["selected_template_id"] = selected
        async_dispatcher_send(hass, template_dispatcher_signal(entry.entry_id))

    if direct:
        @callback
        def direct_catalog_received(event: Event) -> None:
            apply_template_catalog(event.data)

        runtime["unsubscribers"].append(
            hass.bus.async_listen(
                direct_template_catalog_event(str(entry.data[CONF_DEVICE_ID])),
                direct_catalog_received,
            )
        )
        hass.bus.async_fire(
            direct_template_command_event(str(entry.data[CONF_DEVICE_ID])),
            {"action": "catalog"},
        )
    elif runtime["template_state_topic"]:
        @callback
        def mqtt_catalog_received(message) -> None:
            apply_template_catalog(message.payload)

        runtime["unsubscribers"].append(
            await mqtt.async_subscribe(
                hass,
                runtime["template_state_topic"],
                mqtt_catalog_received,
                qos=1,
            )
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA Windows Bridge."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
        for unsubscribe in runtime.get("unsubscribers", []):
            unsubscribe()
    return unload_ok
