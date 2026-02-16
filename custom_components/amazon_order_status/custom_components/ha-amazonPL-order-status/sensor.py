"""Amazon Orders sensors."""

import logging
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntity
from homeassistant.util.dt import as_local

from .const import DOMAIN
from .coordinator import AmazonOrdersCoordinator

_LOGGER = logging.getLogger(__name__)


# statusy jakie widzi użytkownik w HA
STATUSES = [
    "Ordered",
    "Shipped",
    "Out for delivery",
    "Ready for pickup",
    "Delivery attempt",
    "Delivered",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up Amazon Order Status sensors."""
    coordinator: AmazonOrdersCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [AmazonOrderStatusSensor(coordinator, status) for status in STATUSES]
    sensors.append(AmazonOrdersLastUpdatedSensor(coordinator))

    async_add_entities(sensors)


class AmazonOrderStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor representing Amazon orders in a specific status."""

    def __init__(self, coordinator: AmazonOrdersCoordinator, status: str):
        super().__init__(coordinator)

        self.status = status
        self.slug = status.lower().replace(" ", "_")

        self._attr_unique_id = f"amazon_orders_{self.slug}"
        self._attr_name = f"Amazon Orders {status}"
        self._attr_icon = "mdi:package-variant"

    # ------------------------

    @property
    def native_value(self) -> int:
        """Return number of orders in this status."""
        return len(self._orders_for_status())

    # ------------------------

    @property
    def extra_state_attributes(self):
        """Return order details for this status."""
        orders = self._orders_for_status()
        return {
            "order_count": len(orders),
            "orders": orders,
        }

    # ------------------------

    def _orders_for_status(self) -> list[dict]:
        """Return orders matching this sensor's status."""
        if not self.coordinator.data:
            return []

        results = []

        for data in self.coordinator.data:
            if str(data.get("status", "")).lower() != self.slug:
                continue

            results.append(
                {
                    "status": str(data.get("status", "")).replace("_", " ").title(),
                    "product": data.get("product"),
                    "seller": data.get("seller"),
                    "price": data.get("price"),
                    "subject": data.get("subject"),
                    "tracking": data.get("tracking"),
                    "updated": data.get("updated"),
                }
            )

        return results


# =========================================================


class AmazonOrdersLastUpdatedSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing when Amazon orders were last updated."""

    def __init__(self, coordinator: AmazonOrdersCoordinator):
        super().__init__(coordinator)
        self._attr_unique_id = "amazon_orders_last_updated"
        self._attr_name = "Amazon Orders Last Updated"
        self._attr_icon = "mdi:clock-check-outline"

    @property
    def native_value(self):
        """Return timestamp of last update."""
        if not getattr(self.coordinator, "last_check", None):
            return None

        return as_local(self.coordinator.last_check)
