# Sellouts Ticket Monitor

This repository contains a script for monitoring Ticketmaster events and sending email notifications when tickets become available. The main implementation uses **Pyppeteer** and some stealth tweaks to avoid automation detection.

## Directory structure

```
.
├── sellouts/           # Current implementation
│   ├── __init__.py
│   └── monitor.py
├── deprecated/         # Older experiments and Docker files
└── requirements.txt    # Python dependencies
```

The `deprecated/` folder holds previous versions of the code along with some Docker helper scripts. The active code lives in the `sellouts/` package.

## Setup

1. Install Python 3.8 or newer.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with your email credentials and recipient address:

```
EMAIL_ADDRESS=your_email@example.com
EMAIL_PASSWORD=your_email_password
RECIPIENT_EMAIL=recipient@example.com
```

Adjust the `TICKET_URL` constant in `sellouts/monitor.py` to the event you want to monitor.

## Running

Execute the monitor with:

```bash
python -m sellouts.monitor
```

The script will repeatedly reload the event page and send an email when tickets appear.

## License

This project is provided as-is under the MIT License.
