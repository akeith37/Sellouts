import os
import json
import asyncio
import smtplib
import shutil
import random
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import warnings
import pyppeteer
from pyppeteer import launch
from pyppeteer_stealth import stealth
import signal


# Suppress Pyppeteer shutdown coroutine warning
pyppeteer.__pyppeteer_await_shutdown__ = False
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine 'Launcher.killChrome' was never awaited")

# Load environment variables from .env file
load_dotenv()
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

TICKET_URL = "https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"

# Check for required environment variables
required_env_vars = [EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL]
if not all(required_env_vars):
    raise EnvironmentError("One or more required environment variables (EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL) are missing.")

user_data_dir = os.path.join(os.getcwd(), 'user_data')  # Persistent user-data directory for cookies/session
os.makedirs(user_data_dir, exist_ok=True)

# Log the program start time
with open("sellouts_log.txt", "a") as f:
    f.write(f"[START] Program started at {datetime.now()}\n")

# ---- Email Alert ----
async def send_email_alert(details, log_file):
    subject = "Tickets Available!"
    body = f"Tickets have been found!\n{TICKET_URL}\n\nDetails:\n"
    body += "\n".join(details) if details else "(No extra details found)"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        print("Email sent!")
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now()}] EMAIL SENT \n{body}\n\n")
    except Exception as e:
        print("Failed to send email:", e)
        import traceback
        traceback.print_exc()
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now()}] EMAIL FAILED TO SEND: {e}\n\n")

# ---- Ticket availability check logic ----
async def check_ticket_availability(html_content, log_file):
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        match_layers = []
        layer_results = []
        jsonld_details = []
        found = False

        # --- Layer 1: VisuallyHidden result span (multiple occurrences) ---
        try:
            vh_spans = soup.find_all('span', {'role': 'status', 'class': lambda c: c and 'VisuallyHidden' in c})
            if vh_spans:
                vh_found = False
                for idx, vh_span in enumerate(vh_spans):
                    vh_text = vh_span.get_text(strip=True)
                    if vh_text.lower().startswith("0 no results"):
                        layer_results.append(f"[Layer 1: VisuallyHidden] NO TICKETS (span #{idx+1}, text: '{vh_text}')")
                    else:
                        layer_results.append(f"[Layer 1: VisuallyHidden] TICKETS POSSIBLY AVAILABLE (span #{idx+1}, text: '{vh_text}')")
                        vh_found = True
                if vh_found:
                    match_layers.append("Layer 1: VisuallyHidden")
                    found = True
            else:
                layer_results.append("[Layer 1: VisuallyHidden] No VisuallyHidden span found")
        except Exception as e:
            layer_results.append(f"[Layer 1: VisuallyHidden] ERROR: {e}")

        # Only run Layer 2 (HTML seat/price extraction) if tickets found in Layer 1
        if found:
            try:
                # Get event/venue/date from JSON-LD (first MusicEvent found)
                event_name = event_date = venue = address = city = None
                scripts = soup.find_all("script", type="application/ld+json")
                for script in scripts:
                    try:
                        if not script.string:
                            continue
                        data = json.loads(script.string.strip())
                        entries = data if isinstance(data, list) else [data]
                        for entry in entries:
                            if entry.get("@type") == "MusicEvent":
                                event_name = entry.get("name")
                                event_date = entry.get("startDate")
                                venue = entry.get("location", {}).get("name")
                                address = entry.get("location", {}).get("address", {}).get("streetAddress")
                                city = entry.get("location", {}).get("address", {}).get("addressLocality")
                                break
                        if event_name:
                            break
                    except Exception:
                        continue
                # Scan all divs with aria-label for seat/price info
                seat_divs = soup.find_all('div', attrs={'aria-label': True})
                import re
                found_seat = False
                for div in seat_divs:
                    aria = div['aria-label']
                    aria_lower = aria.lower()
                    if any(k in aria_lower for k in ["section", "row", "standing", "circle", "pitch", "general admission"]):
                        # Extract price (e.g. £332.22 or $100.00)
                        price_match = re.search(r'[£$€]([\d,.]+)', aria)
                        price = price_match.group(1) if price_match else 'N/A'
                        currency = ''
                        if '£' in aria: currency = 'GBP'
                        elif '$' in aria: currency = 'USD'
                        elif '€' in aria: currency = 'EUR'
                        # Extract seat info (remove price and 'Select Resale Tickets' etc)
                        seat_info = aria
                        seat_info = re.sub(r'Select (Resale )?Tickets', '', seat_info, flags=re.I).strip()
                        seat_info = re.sub(r'^[£$€][\d,.]+,?\s*', '', seat_info).strip()
                        details_str = f"Event: {event_name or 'N/A'} | Date: {event_date or 'N/A'} | Venue: {venue or 'N/A'}, {address or ''}, {city or ''} | "
                        details_str += f"Price: {price} {currency} | Seat: {seat_info}"
                        jsonld_details.append(details_str)
                        found_seat = True
                if found_seat:
                    layer_results.append("[Layer 2: HTML] Ticket seat/price details extracted from HTML.")
                    match_layers.append("Layer 2: HTML")
                    layer_results.extend([f"[Layer 2: HTML] {d}" for d in jsonld_details])
                else:
                    layer_results.append("[Layer 2: HTML] No seat/price details found in HTML.")
            except Exception as e:
                layer_results.append(f"[Layer 2: HTML] ERROR: {e}")

        # # Only write to log if tickets are found
        # if found:
        #     # Save HTML content to a new uniquely named file with timestamp and a counter
        #     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        #     counter = 1
        #     base_filename = f"tickets_found_{timestamp}"
        #     html_filename = f"{base_filename}.txt"
        #     while os.path.exists(html_filename):
        #         html_filename = f"{base_filename}_{counter}.txt"
        #         counter += 1
        #     with open(html_filename, "w", encoding="utf-8") as html_file:
        #         html_file.write(html_content)
        #     with open(log_file, "a") as f:
        #         f.write(f"[{datetime.now()}] TICKETS FOUND\n")
        #         for line in layer_results:
        #             f.write(line + "\n")
        #         if jsonld_details:
        #             f.write("Details:\n" + "\n".join(jsonld_details) + "\n")
        #         f.write(f"HTML snapshot saved to: {html_filename}\n")
        #         f.write("-" * 60 + "\n")
            # print("Results written to log file.")

        return found, jsonld_details if found else []
    except Exception as e:
        print("Error in check_ticket_availability:", e)
        import traceback
        traceback.print_exc()
        return False, []

# ---- Shutdown and Cleanup ----
async def shutdown(browser):
    try:
        if browser:
            await browser.close()
    except Exception as e:
        print("Error during browser shutdown:", e)
        import traceback
        traceback.print_exc()

def get_chrome_path():
    # Return path to latest Chrome/Chromium if found, else None to use Pyppeteer's default
    for name in ["chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
        path = shutil.which(name)
        if path:
            return path
    return None

# ---- Entry Point ----
async def main():
    chrome_path = get_chrome_path()
    browser = None
    shutdown_event = asyncio.Event()

    def handle_signal(signum, frame):
        print(f"\nReceived signal {signum}. Initiating shutdown...")
        shutdown_event.set()

    # Register signal handlers for graceful shutdown (CTRL+C, taskkill, etc.)
    signal.signal(signal.SIGINT, handle_signal)   # CTRL+C
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, handle_signal)  # taskkill or kill

    try:
        browser = await launch({
            "headless": False,
            "userDataDir": user_data_dir,  # Store cookies/session info
            "executablePath": chrome_path,
            "args": [
                "--start-maximized",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ],
            "ignoreDefaultArgs": ["--enable-automation"],
        })
        page = (await browser.pages())[0]
        await page.setUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/114.0.5735.110 Safari/537.36'
        )
        await stealth(page)
        await page.evaluateOnNewDocument("""
            (() => {
            // 1. Hide the `navigator.webdriver` property to avoid Selenium/Pyppeteer detection
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true
            });
            // 2. Spoof `navigator.languages` to a typical user-preferred languages array
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            // 3. Spoof `navigator.platform` to a common platform value
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
            // 4. Spoof `navigator.deviceMemory` to a typical memory size in GB
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
            // 5. Spoof `navigator.hardwareConcurrency` to a typical number of CPU cores
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 4
            });
            // 6. Spoof `navigator.plugins` to simulate installed plugins (avoid empty plugins list)
            if (navigator.plugins && navigator.plugins.length === 0) {
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3]
                });
            }
            // 7. Canvas fingerprint spoofing: override toDataURL to return a fake image in certain cases
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
                value: function(...args) {
                    const [type, ...rest] = args;
                    if (type === 'image/png' && this.width === 220 && this.height === 30) {
                        return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAANwAAAAeCAIAAADIGOdpAAAAbElEQVR4nO3SMQEAIAzAMMC/5/FjgB6Jgh7dM7Og5PwOgJcpyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkXOL+AznTluWxAAAAAElFTkSuQmCC';
                    }
                    return originalToDataURL.apply(this, args);
                }
            });
            // 8. Audio fingerprint spoofing: override AudioBuffer.getChannelData to return altered data
            const originalGetChannelData = AudioBuffer.prototype.getChannelData;
            Object.defineProperty(AudioBuffer.prototype, 'getChannelData', {
                value: function(...args) {
                    const originalBuffer = originalGetChannelData.apply(this, args);
                    const newBuffer = new Float32Array(originalBuffer);
                    if (newBuffer.length > 0) {
                        newBuffer[0] += 0.0001;
                    }
                    return newBuffer;
                }
            });
        })();
        """)
        await page.goto(TICKET_URL, {
            'waitUntil': 'networkidle2',
            'timeout': 45000
        })
        await page.waitForSelector("script[type='application/ld+json']")
        await check_tickets_loop(page, shutdown_event)
    except Exception as e:
        print("Fatal error in main():", e)
        import traceback
        traceback.print_exc()
    finally:
        await shutdown(browser)

# ---- Check Tickets Loop ----
async def check_tickets_loop(page, shutdown_event):
    log_file = "sellouts_log.txt"
    check_count = 0
    while not shutdown_event.is_set():
        try:
            print(f"Checking tickets... (check count: {check_count})")
            await asyncio.wait_for(page.reload({'waitUntil': 'networkidle2'}), timeout=30)
            await asyncio.wait_for(page.waitForSelector("script[type='application/ld+json']"), timeout=15)
            html = await page.content()
            found, details = await check_ticket_availability(html, log_file)
            check_count += 1
            if found:
                print("Tickets found! Sending email alert...")
                await send_email_alert(details, log_file)
            else:
                print("No tickets found.")
            check_interval = random.uniform(2, 5)
            print(f"Waiting {check_interval:.1f} seconds...\n")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=check_interval)
            except asyncio.TimeoutError:
                pass
        except asyncio.TimeoutError:
            print("Timeout occurred while waiting for page reload, selector, or interval.")
            import traceback
            traceback.print_exc()
            continue
        except Exception as e:
            print("Unexpected error in check_tickets_loop:", e)
            import traceback
            traceback.print_exc()
            continue

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Exiting gracefully.")
    except Exception as e:
        print("Fatal error in __main__:", e)
        import traceback
        traceback.print_exc()
