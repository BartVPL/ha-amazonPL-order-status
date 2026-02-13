"""Amazon Orders Data Coordinator."""

from __future__ import annotations

import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header
from typing import Dict

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
from bs4 import BeautifulSoup

from .const import CONF_MARK_AS_READ

_LOGGER = logging.getLogger(__name__)

LAST_CHECK_KEY = "last_check"
STORAGE_VERSION = 1
STORAGE_KEY = "amazon_order_status"
ORDERS_KEY = "orders"

ORDER_REGEX = re.compile(r"[0-9]{3}\-[0-9]{7}\-[0-9]{7}", re.IGNORECASE)


# =====================================================
# STATUS FRAZY — WSZYSTKIE OBSŁUGIWANE
# =====================================================

STATUS_PATTERNS = [
    (r"zamówion", "Ordered"),
    (r"dziękujemy za złożenie zamówienia", "Ordered"),

    (r"wysłan", "Shipped"),
    (r"nadano", "Shipped"),

    (r"przekazan.*do doręczenia", "Out for delivery"),
    (r"wydan.*do doręczenia", "Out for delivery"),

    (r"próba dostarczenia", "Delivery attempt"),
    (r"podjęto próbę dostarczenia", "Delivery attempt"),

    (r"odebran", "Picked up"),

    (r"gotowa do odbioru", "Ready for pickup"),
    (r"przesyłka gotowa do odbioru", "Ready for pickup"),

    (r"dostarczon", "Delivered"),
    (r"doręczon", "Delivered"),
]


def detect_status(text: str) -> str | None:
    text = text.lower()

    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text):
            return status

    return None


# =====================================================


class AmazonOrdersCoordinator(DataUpdateCoordinator):
    """Coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._orders: Dict[str, dict] = {}

        interval_minutes = entry.options.get("update_interval", 5)

        super().__init__(
            hass,
            _LOGGER,
            name="Amazon Order Status",
            update_interval=timedelta(minutes=interval_minutes),
        )

    async def async_load_last_check(self):
        stored = await self._store.async_load()
        if stored and LAST_CHECK_KEY in stored:
            return datetime.fromisoformat(stored[LAST_CHECK_KEY])
        return None

    async def async_load_stored_orders(self):
        stored = await self._store.async_load()
        self._orders = stored.get(ORDERS_KEY, {}) if stored else {}

    async def async_save_state(self, last_check):
        await self._store.async_save(
            {
                LAST_CHECK_KEY: last_check.isoformat(),
                ORDERS_KEY: self._orders,
            }
        )

    async def _async_update_data(self):
        if not self._orders:
            await self.async_load_stored_orders()

        last_check = await self.async_load_last_check()
        now = datetime.now(timezone.utc)

        await self.hass.async_add_executor_job(
            self._fetch_emails,
            last_check,
            now,
        )

        await self.async_save_state(now)

        return list(self._orders.values())

    # =====================================================

    def _fetch_emails(self, last_check, now):
        email_addr = self.entry.data["email"]
        password = self.entry.data["password"]
        imap_server = self.entry.data["imap_server"]

        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(email_addr, password)
        mail.select("INBOX")

        since = last_check or (now - timedelta(days=30))
        since_date = since.strftime("%d-%b-%Y")

        typ, data = mail.search(None, f'(SINCE "{since_date}")')

        if typ != "OK":
            mail.logout()
            return

        for num in data[0].split():
            typ, msg_data = mail.fetch(num, "(RFC822)")
            if typ != "OK":
                continue

            msg = message_from_bytes(msg_data[0][1])
            subject = self._decode(msg.get("Subject", ""))
            body = self._get_text(msg)
            html = self._get_html(msg)

            status = detect_status(subject) or detect_status(body) or detect_status(html)

            if not status:
                continue

            order_ids = ORDER_REGEX.findall(body + html)
            if not order_ids:
                continue

            product = self._extract_product(body + html)
            seller = self._extract_seller(body + html)
            tracking = self._extract_tracking(html)

            for oid in order_ids:
                self._orders[oid] = {
                    "status": status,
                    "product": product,
                    "seller": seller,
                    "tracking": tracking,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }

        mail.logout()

    # =====================================================

    def _decode(self, value):
        parts = decode_header(value)
        text = ""
        for part, enc in parts:
            if isinstance(part, bytes):
                text += part.decode(enc or "utf-8", errors="ignore")
            else:
                text += part
        return text

    def _get_text(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        return ""

    def _get_html(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        return ""

    # =====================================================
    # EXTRACTION
    # =====================================================

    def _extract_product(self, text):
        m = re.search(r"(Produkt|Item)[^\n:]*:\s*(.+)", text, re.I)
        return m.group(2).strip() if m else None

    def _extract_seller(self, text):
        m = re.search(r"(Sprzedawca|Sold by)[^\n:]*:\s*(.+)", text, re.I)
        return m.group(2).strip() if m else None

    def _extract_tracking(self, html):
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            if "track" in link["href"]:
                return link["href"]
        return None
    async def async_set_retention_days(self, days: int):
        return

    async def async_update_interval(self, minutes: int):
        self.update_interval = timedelta(minutes=minutes)