"""Amazon Orders Data Coordinator."""

from __future__ import annotations

import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

ORDER_REGEX = re.compile(r"[0-9]{3}\-[0-9]{7}\-[0-9]{7}", re.IGNORECASE)

# =====================================================
# STATUS DETEKCJA
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

    (r"odebran", "Delivered"),
    (r"dostarczon", "Delivered"),
    (r"doręczon", "Delivered"),

    (r"gotowa do odbioru", "Ready for pickup"),
    (r"przesyłka gotowa do odbioru", "Ready for pickup"),
]


def detect_status(text: str) -> str | None:
    text = text.lower()

    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text):
            return status

    return None


# =====================================================
# COORDINATOR
# =====================================================

class AmazonOrdersCoordinator(DataUpdateCoordinator):
    """Coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry

        interval_minutes = entry.options.get("update_interval", 5)

        super().__init__(
            hass,
            _LOGGER,
            name="Amazon Order Status",
            update_interval=timedelta(minutes=interval_minutes),
        )

    # =====================================================
    # GŁÓWNY UPDATE
    # =====================================================

    async def _async_update_data(self):
        return await self.hass.async_add_executor_job(self._fetch_emails)

    # =====================================================
    # IMAP FETCH
    # =====================================================

    def _fetch_emails(self):
        email_addr = self.entry.data["email"]
        password = self.entry.data["password"]
        imap_server = self.entry.data["imap_server"]
        port = self.entry.data.get("imap_port", 993)

        orders = {}

        try:
            mail = imaplib.IMAP4_SSL(imap_server, port)
            mail.login(email_addr, password)
            mail.select("INBOX")

            typ, data = mail.search(None, "ALL")
            if typ != "OK":
                return []

            for num in data[0].split():
                typ, msg_data = mail.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue

                msg = message_from_bytes(msg_data[0][1])

                subject = self._decode(msg.get("Subject", ""))
                body = self._get_text(msg)
                html = self._get_html(msg)

                combined = f"{subject} {body} {html}"

                status = detect_status(combined)

                if not status:
                    continue

                # AUTO USUWANIE DOSTARCZONYCH
                if status == "Delivered":
                    continue

                order_ids = ORDER_REGEX.findall(combined)
                if not order_ids:
                    continue

                product = self._extract_product(combined)
                seller = self._extract_seller(combined)
                tracking = self._extract_tracking(html)

                for oid in order_ids:
                    orders[oid] = {
                        "status": status,
                        "product": product,
                        "seller": seller,
                        "tracking": tracking,
                        "updated": datetime.now(timezone.utc).isoformat(),
                    }

            mail.logout()

        except Exception as e:
            _LOGGER.error("Amazon mail fetch error: %s", e)
            return []

        # KLUCZOWE: NADPISUJEMY LISTĘ (SYNC)
        return list(orders.values())

    # =====================================================
    # PARSING HELPERS
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
    # EKSTRAKCJA
    # =====================================================

    def _extract_product(self, text):
        soup = BeautifulSoup(text, "html.parser")
        links = soup.find_all("a")
        for a in links:
            if a.text and len(a.text.strip()) > 5:
                return a.text.strip()
        return None

    def _extract_seller(self, text):
        m = re.search(r"(Sprzedawca|Sold by)[^\n:]*:\s*(.+)", text, re.I)
        return m.group(2).strip() if m else None

    def _extract_tracking(self, html):
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            if "track" in link["href"] or "tracking" in link["href"]:
                return link["href"]
        return None

    # =====================================================
    # OPTIONS SUPPORT (żeby options_flow nie wywalał błędów)
    # =====================================================

    async def async_set_retention_days(self, days: int):
        return

    async def async_update_interval(self, minutes: int):
        self.update_interval = timedelta(minutes=minutes)

    async def async_set_mark_as_read(self, value: bool):
        return
