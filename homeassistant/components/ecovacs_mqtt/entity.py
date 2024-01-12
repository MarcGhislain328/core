"""Ecovacs mqtt entity module."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from deebot_client.capabilities import Capabilities
from deebot_client.device import Device
from deebot_client.events import AvailabilityEvent
from deebot_client.events.base import Event

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN

_EntityDescriptionT = TypeVar("_EntityDescriptionT", bound=EntityDescription)
CapabilityT = TypeVar("CapabilityT")
EventT = TypeVar("EventT", bound=Event)


@dataclass(kw_only=True, frozen=True)
class EcovacsEntityDescription(
    EntityDescription,
    Generic[CapabilityT],
):
    """Ecovacs entity description."""

    capability_fn: Callable[[Capabilities], CapabilityT | None]


class EcovacsEntity(Entity, Generic[CapabilityT, _EntityDescriptionT]):
    """Ecovacs entity."""

    entity_description: _EntityDescriptionT

    _attr_should_poll = False
    _attr_has_entity_name = True
    _always_available: bool = False
    _subscribed_events: set[type[Event]] = set()

    def __init__(
        self,
        device: Device,
        capability: CapabilityT,
        entity_description: _EntityDescriptionT | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize entity."""
        super().__init__(**kwargs)
        if entity_description:
            self.entity_description = entity_description
        elif not hasattr(self, "entity_description"):
            raise ValueError(
                '"entity_description" must be either set as class variable or passed on init!'
            )

        self._device = device
        self._capability = capability
        self._attr_unique_id = (
            f"{self._device.device_info.did}_{self.entity_description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device specific attributes."""
        device_info = self._device.device_info
        info = DeviceInfo(
            identifiers={(DOMAIN, device_info.did)},
            manufacturer="Ecovacs",
            sw_version=self._device.fw_version,
            serial_number=device_info.name,
        )

        if nick := device_info.api_device_info.get("nick"):
            info["name"] = nick

        if model := device_info.api_device_info.get("deviceName"):
            info["model"] = model

        if mac := self._device.mac:
            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, mac)}

        return info

    async def async_added_to_hass(self) -> None:
        """Set up the event listeners now that hass is ready."""
        await super().async_added_to_hass()

        if not self._always_available:

            async def on_available(event: AvailabilityEvent) -> None:
                self._attr_available = event.available
                self.async_write_ha_state()

            self._subscribe(AvailabilityEvent, on_available)

    def _subscribe(
        self,
        event_type: type[EventT],
        callback: Callable[[EventT], Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe to events."""
        self._subscribed_events.add(event_type)
        self.async_on_remove(self._device.events.subscribe(event_type, callback))

    async def async_update(self) -> None:
        """Update the entity.

        Only used by the generic entity update service.
        """
        for event_type in self._subscribed_events:
            self._device.events.request_refresh(event_type)
