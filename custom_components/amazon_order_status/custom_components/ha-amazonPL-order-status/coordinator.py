"""Amazon Orders Coordinator."""

from __future__ import annotations

import logging
import imaplib
import email
import re
from datetime import datetime, timedelta
from email.header import decode_header

from bs4 import BeautifulSoup

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import utcnow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


STATUS_MAP = {
    "ordered": ["zamówione", "ordered", "dziękujemy za złożenie zamówienia"],
    "shipped": ["wysłane", "shipped"],
    "out_for_delivery": [
        "przekazano do doręczenia",
        "out for delivery",
        "kurier już jedzie",
    ],
    "delivery_attempt": [
        "próba dostarczenia",
        "delivery attempt",
        "podjęto próbę dostarczenia",
    ],
    "ready_for_pickup": [
        "gotowa do odbioru",
        "ready for pickup",
    ],
    "delivered": [
        "dostarczona",
        "delivered",
        "odebrano",
    ],
}


def _decode(value):
    if not value:
        return ""
    decoded = decode_header(value)
    return "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in decoded
    )


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def _extract_product(soup: BeautifulSoup):
    link = soup.select_one("a[href*='/dp/']")
    if link:
        return link.get_text(strip=True)
    return None


def _extract_price(text: str):
    m = re.search(r"(\d+[,.]\d+)\s?zł", text)
    if m:
        return m.group(1) + " zł"
    return None


def _extract_seller(text: str):
    m = re.search(r"Sprzedawca[:\-]\s*(.+?)(?:Stan:|Ilość:|$)", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def _extract_tracking(soup: BeautifulSoup):
    link = soup.find("a", string=re.compile("śledź|track", re.I))
    if link and link.get("href"):
        return link["href"]
    return None


def _detect_status(text: str):
    text = text.lower()
    for status, phrases in STATUS_MAP.items():
        for p in phrases:
            if p in text:
                return status
    return "ordered"


class AmazonOrdersCoordinator(DataUpdateCoordinator):
    """Coordinator fetching Amazon emails."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.data = []
        self.last_check = None

        interval = entry.options.get("update_interval", 5)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    async def _async_update_data(self):
        return await self.hass.async_add_executor_job(self._fetch_orders)

    def _fetch_orders(self):
        cfg = self.entry.data
        orders = []

        imap = imaplib.IMAP4_SSL(cfg["imap_server"], cfg["imap_port"])
        imap.login(cfg["username"], cfg["password"])
        imap.select("INBOX")

        typ, data = imap.search(None, '(FROM "amazon")')

        for num in data[0].split():
            typ, msg_data = imap.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode(msg.get("Subject"))
            body = ""

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")

            soup = BeautifulSoup(body, "html.parser")
            text = _clean_html(body)

            status = _detect_status(subject + " " + text)

            if status == "delivered":
                continue

            product = _extract_product(soup)
            price = _extract_price(text)
            seller = _extract_seller(text)
            tracking = _extract_tracking(soup)

            orders.append(
                {
                    "status": status,
                    "product": product,
                    "price": price,
                    "seller": seller,
                    "subject": subject,
                    "tracking": tracking,
                    "updated": utcnow().isoformat(),
                }
            )

        imap.logout()

        self.last_check = utcnow()
        return orders

    async def async_set_mark_as_read(self, value: bool):
        self.entry.options["mark_as_read"] = value

    async def async_set_retention_days(self, days: int):
        self.entry.options["delivered_retention_days"] = days

    async def async_update_interval(self, minutes: int):
        self.update_interval = timedelta(minutes=minutes)
