"""Options flow for Amazon Order Status integration."""

from homeassistant import config_entries
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN


class AmazonOrderStatusOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            new_options = dict(self._config_entry.options)
            new_options.update(user_input)

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options=new_options,
            )

            coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)

            if coordinator:
                if "delivered_retention_days" in user_input and hasattr(coordinator, "async_set_retention_days"):
                    await coordinator.async_set_retention_days(user_input["delivered_retention_days"])

                if "update_interval" in user_input and hasattr(coordinator, "async_update_interval"):
                    await coordinator.async_update_interval(user_input["update_interval"])

                if "mark_as_read" in user_input:
                    if hasattr(coordinator, "async_set_mark_as_read"):
                        await coordinator.async_set_mark_as_read(user_input["mark_as_read"])
                    else:
                        # fallback, jeśli coordinator ma tylko pole
                        setattr(coordinator, "_mark_as_read", user_input["mark_as_read"])

            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    "delivered_retention_days",
                    default=options.get("delivered_retention_days", 30),
                ): vol.All(int, vol.Range(min=1, max=365)),
                vol.Required(
                    "update_interval",
                    default=options.get("update_interval", 5),
                ): vol.All(int, vol.Range(min=1, max=120)),
                vol.Required(
                    "mark_as_read",
                    default=options.get("mark_as_read", True),
                ): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
