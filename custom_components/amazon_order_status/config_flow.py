"""Config flow for Amazon Order Status integration."""

from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
import imaplib
import socket
import logging

from .const import DOMAIN
from .options_flow import AmazonOrderStatusOptionsFlow

_LOGGER = logging.getLogger(__name__)


# =========================================================
# VALIDATION
# =========================================================

async def validate_imap_config(hass, host, port, username, password):
    """Test connection to IMAP server."""

    def _validate():
        try:
            port = int(port or 993)

            imap = imaplib.IMAP4_SSL(host, port, timeout=15)
            imap.login(username, password)
            imap.select("INBOX")
            imap.logout()

            return None

        except imaplib.IMAP4.error as e:
            _LOGGER.error("IMAP auth error: %s", e)
            return "invalid_auth"

        except socket.gaierror as e:
            _LOGGER.error("DNS error: %s", e)
            return "cannot_connect"

        except OSError as e:
            _LOGGER.error("Connection error: %s", e)
            return "cannot_connect"

        except Exception as e:
            _LOGGER.exception("Unknown IMAP error")
            return "unknown"

    return await hass.async_add_executor_job(_validate)


# =========================================================
# FLOW
# =========================================================

class AmazonOrdersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:

            error = await validate_imap_config(
                self.hass,
                user_input["imap_server"],
                user_input.get("imap_port"),
                user_input["username"],
                user_input["password"],
            )

            if error is None:
                await self.async_set_unique_id(user_input["email"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input["email"],
                    data={
                        "email": user_input["email"],
                        "imap_server": user_input["imap_server"],
                        "username": user_input["username"],
                        "password": user_input["password"],
                        "imap_port": user_input.get("imap_port", 993),
                    },
                    options={
                        "update_interval": user_input.get("poll_interval", 5),
                        "delivered_retention_days": 30,
                        "mark_as_read": user_input.get("mark_as_read", True),
                    },
                )

            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("imap_server"): str,
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Optional("imap_port", default=993): int,
                vol.Optional("poll_interval", default=5): int,
                vol.Optional("mark_as_read", default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # =========================================================

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return AmazonOrderStatusOptionsFlow(config_entry)