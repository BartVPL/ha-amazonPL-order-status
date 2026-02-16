import imaplib
import re
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email import message_from_bytes

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_MARK_AS_READ

_LOGGER = logging.getLogger(__name__)


# =========================================================
# STATUS MAP
# =========================================================

STATUS_MAP = {
    "ordered": [
        "zamówione",
        "zamówienie",
        "order",
        "dziękujemy za złożenie zamówienia",
    ],
    "shipped": [
        "wysłane",
        "wysłano",
        "shipped",
    ],
    "out_for_delivery": [
        "przekazano do doręczenia",
        "w doręczeniu",
        "out for delivery",
    ],
    "delivery_attempt": [
        "próba dostarczenia",
        "podjęto próbę",
        "delivery attempt",
    ],
    "ready_for_pickup": [
        "gotowa do odbioru",
        "ready for pickup",
    ],
    "delivered": [
        "dostarczona",
        "doręczona",
        "odebrano",
        "delivered",
    ],
}


ORDER_ID_RE = re.compile(r"\d{3}-\d{7}-\d{7}")
PRICE_RE = re.compile(r"(\d+[.,]\d{2})\s?zł", re.I)


# =========================================================
# COORDINATOR
# =========================================================

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
        self.delivered_retention_days = entry.options.get("delivered_retention_days", 30)
        self.last_check = None

    # =========================================================

    async def _async_update_data(self):
        now = datetime.now(timezone.utc)

        await self.hass.async_add_executor_job(
            self._fetch_and_parse_emails,
            self.last_check,
            now,
        )

        self.last_check = now
        return list(self._orders.values())

    # =========================================================

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

            _LOGGER.debug("Amazon mail subject: %s", subject)

            status = self._detect_status(subject)
            if not status:
                continue

            order_ids = ORDER_ID_RE.findall(subject + body)
            if not order_ids:
                continue

            product = self._extract_product(body)
            price = self._extract_price(body)

            for oid in order_ids:

                if status.lower() == "delivered":
                    self._orders.pop(oid, None)
                    continue

                self._orders[oid] = {
                    "status": status,
                    "product": product,
                    "price": price,
                    "seller": "Amazon",
                    "subject": subject,
                    "tracking": None,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }

            if self._mark_as_read:
                mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()

    # =========================================================
    # STATUS DETECTION
    # =========================================================

    def _detect_status(self, subject):

        if not subject:
            return None

        subject_lower = subject.lower()

        # 1️⃣ prefix before colon
        m = re.match(r"(.+?):", subject_lower)
        if m:
            prefix = m.group(1).strip()

            for status, words in STATUS_MAP.items():
                for word in words:
                    if word in prefix:
                        return self._format(status)

        # 2️⃣ fallback full subject scan
        for status, words in STATUS_MAP.items():
            for word in words:
                if word in subject_lower:
                    return self._format(status)

        return None

    # =========================================================

    def _format(self, key):
        return {
            "ordered": "Ordered",
            "shipped": "Shipped",
            "out_for_delivery": "Out for delivery",
            "delivery_attempt": "Delivery attempt",
            "ready_for_pickup": "Ready for pickup",
            "delivered": "Delivered",
        }.get(key)

    # =========================================================
    # TEXT EXTRACTION
    # =========================================================

    def _decode(self, value):
        decoded = ""
        for part, enc in decode_header(value):
            if isinstance(part, bytes):
                decoded += part.decode(enc or "utf-8", errors="ignore")
            else:
                decoded += part
        return decoded

    # ---------------------------------------------------------

    def _get_text(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
        return ""

    # ---------------------------------------------------------
    # PRODUCT
    # ---------------------------------------------------------

    def _extract_product(self, body):

        if not body:
            return None

        m = re.search(r"\*\s*(.+)", body)
        if not m:
            return None

        product = m.group(1).strip()
        return product[:100]

    # ---------------------------------------------------------
    # PRICE
    # ---------------------------------------------------------

    def _extract_price(self, body):

        if not body:
            return None

        m = PRICE_RE.search(body)
        if m:
            return m.group(1) + " zł"

        return None

    # =========================================================
    # OPTIONS FLOW SUPPORT
    # =========================================================

    async def async_set_retention_days(self, days: int):
        self.delivered_retention_days = days

    async def async_update_interval(self, minutes: int):
        self.update_interval = timedelta(minutes=minutes)

    async def async_set_mark_as_read(self, value: bool):
        self._mark_as_read = value