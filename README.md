# ha-amazonPL-order-status

Home Assistant custom integration that tracks Amazon delivery/order statuses by reading notification emails via IMAP.

## Features
- Works with Polish and English Amazon emails (PL/EN parsing).
- Detects status from both email subject and body (HTML/text).
- Exposes sensors per status (counts + order list attributes).
- Extracts product name and seller when available.
- IMAP compatible (e.g. Gmail with App Password / 2FA).

## Statuses supported (examples)
- Ordered / Zamówione
- Shipped / Wysłane
- Out for delivery / Przekazano do doręczenia / Wydana do doręczenia
- Delivery attempt / Próba dostarczenia
- Ready for pickup / Przesyłka gotowa do odbioru
- Picked up / Odebrano
- Delivered / Dostarczono / Doręczono

## Installation (HACS)
1. HACS → Integrations → 3 dots → Custom repositories
2. Add this repository URL, category: Integration
3. Install → restart Home Assistant

## Credits
Based on the original integration by @koconnorgit:
https://github.com/koconnorgit/ha-amazon-order-status

