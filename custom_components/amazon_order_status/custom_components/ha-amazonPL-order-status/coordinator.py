import imaplib
import email
import re
import html
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email import message_from_bytes
from bs4 import BeautifulSoup
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, CONF_MARK_AS_READ

_LOGGER = logging.getLogger(__name__)

STATUS_MAP = {
    "zamówione": "Ordered",
    "wysłane": "Shipped",
    "przekazana do doręczenia": "Out for delivery",
    "przekazano do doręczenia": "Out for delivery",
    "w drodze": "Shipped",
    "odebrana": "Delivered",
    "odebrano": "Delivered",
    "gotowa do odbioru": "Ready for pickup",
    "delivery attempt": "Delivery attempt",
}


ORDER_ID_RE = re.compile(r"\d{3}-\d{7}-\d{7}")


class AmazonOrdersCoordinator(DataUpdateCoordinator):

    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name="Amazon Orders",
            update_interval=timedelta(minutes=entry.options.get("update_interval", 5)),
        )

        self.entry = entry
        self._orders = {}
        self._mark_as_read = entry.options.get(CONF_MARK_AS_READ, True)
        self.delivered_retention_days = entry.options.get(
            "delivered_retention_days", 30
        )
        self.last_check = None

    async def _async_update_data(self):
        now = datetime.now(timezone.utc)
        await self.hass.async_add_executor_job(
            self._fetch_and_parse_emails, self.last_check, now
        )
        self.last_check = now
        return list(self._orders.values())

    # -----------------------------------------------------

    def _fetch_and_parse_emails(self, last_check, now):

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
            html_body = self._get_html(msg)
            combined = f"{subject}\n{body}\n{html_body}".lower()

            status = self._detect_status(combined)
            if not status:
                continue

            order_ids = ORDER_ID_RE.findall(combined)
            if not order_ids:
                continue

            product = self._extract_product(body, html_body, subject)
            seller = self._extract_seller(body + html_body)
            tracking = self._extract_tracking(html_body)

            for oid in order_ids:
                if status.lower() == "delivered":
                    self._orders.pop(oid, None)
                    continue

                self._orders[oid] = {
                    "status": status,
                    "product": product,
                    "seller": seller,
                    "tracking": tracking,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }

            if self._mark_as_read:
                mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()

    # -----------------------------------------------------

    def _detect_status(self, text):
        for key, val in STATUS_MAP.items():
            if key in text:
                return val
        return None

    # -----------------------------------------------------

    def _decode(self, value):
        decoded = ""
        for part, enc in decode_header(value):
            if isinstance(part, bytes):
                decoded += part.decode(enc or "utf-8", errors="ignore")
            else:
                decoded += part
        return decoded

    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # EXTRACTION
    # -----------------------------------------------------

    def _extract_product(self, body, html_body, subject):

        # 1️⃣ subject: "Wysłane: Produkt"
        m = re.search(r":\s*[„\"]?(.+?)[”\"]?$", subject)
        if m:
            return m.group(1).strip()

        # 2️⃣ tekst maila lista produktów "* produkt"
        m = re.search(r"\*\s*(.+)", body)
        if m:
            return m.group(1).strip()

        # 3️⃣ html fallback
        soup = BeautifulSoup(html_body, "html.parser")
        for link in soup.find_all("a"):
            text = link.get_text(strip=True)
            if len(text) > 5 and "amazon" not in text.lower():
                return text

        return None

    # -----------------------------------------------------

    def _extract_seller(self, text):
        m = re.search(r"(sprzedawca|sold by)[^\n:]*:\s*(.+)", text, re.I)
        return m.group(2).strip() if m else None

    # -----------------------------------------------------

    def _extract_tracking(self, html_body):
        soup = BeautifulSoup(html_body, "html.parser")
        for link in soup.find_all("a", href=True):
            href = html.unescape(link["href"])
            if "progress-tracker" in href:
                return href
        return None

    # -----------------------------------------------------

    async def async_set_retention_days(self, days: int):
        self.delivered_retention_days = days

    async def async_update_interval(self, minutes: int):
        self.update_interval = timedelta(minutes=minutes)

    async def async_set_mark_as_read(self, value: bool):
        self._mark_as_read = value
