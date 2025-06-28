import os
import json
import asyncio
import smtplib
import shutil
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import warnings
import pyppeteer
from pyppeteer import launch
from pyppeteer_stealth import stealth


# Suppress Pyppeteer shutdown coroutine warning
pyppeteer.__pyppeteer_await_shutdown__ = False
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine 'Launcher.killChrome' was never awaited")

# Load environment variables from .env file
load_dotenv()
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
CHECK_INTERVAL = 60  # seconds between checking again

TICKET_URL = "https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"

# Check for required environment variables
required_env_vars = [EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL]
if not all(required_env_vars):
    raise EnvironmentError("One or more required environment variables (EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL) are missing.")

user_data_dir = os.path.join(os.getcwd(), 'user_data')  # Persistent user-data directory for cookies/session
os.makedirs(user_data_dir, exist_ok=True)

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
            else:
                layer_results.append("[Layer 1: VisuallyHidden] No VisuallyHidden span found")
        except Exception as e:
            layer_results.append(f"[Layer 1: VisuallyHidden] ERROR: {e}")

        # --- Layer 2: Result count span from UI indicator ---
        try:
            result_span = soup.find('span', class_=lambda c: c and 'resultCount' in c)
            if result_span:
                text = result_span.get_text(strip=True).lower()
                if text.startswith("0 no results"):
                    layer_results.append(f"[Layer 2: resultCount] NO TICKETS (text: '{text}')")
                elif "result" in text and "no" not in text:
                    layer_results.append(f"[Layer 2: resultCount] TICKETS POSSIBLY AVAILABLE (text: '{text}')")
                    match_layers.append("Layer 2: resultCount")
                else:
                    layer_results.append(f"[Layer 2: resultCount] UNRECOGNIZED RESULT (text: '{text}')")
            else:
                layer_results.append("[Layer 2: resultCount] No resultCount span found")
        except Exception as e:
            layer_results.append(f"[Layer 2: resultCount] ERROR: {e}")

        # --- Layer 3: Sold-Out Banner ---
        try:
            banner = soup.find('span', {'data-testid': 'message-bar-text'})
            if banner:
                banner_text = banner.get_text(strip=True).lower()
                if "no tickets currently available" in banner_text:
                    layer_results.append(f"[Layer 3: sold-out banner] NO TICKETS (text: '{banner_text}')")
                else:
                    layer_results.append(f"[Layer 3: sold-out banner] TICKETS POSSIBLY AVAILABLE (text: '{banner_text}')")
                    match_layers.append("Layer 3: sold-out banner")
            else:
                layer_results.append("[Layer 3: sold-out banner] No sold-out banner found")
        except Exception as e:
            layer_results.append(f"[Layer 3: sold-out banner] ERROR: {e}")

        # --- Layer 4: JSON-LD ticket offer ---
        try:
            scripts = soup.find_all("script", type="application/ld+json")
            found_in_json = False
            for script in scripts:
                try:
                    if not script.string:
                        continue
                    data = json.loads(script.string.strip())
                    entries = data if isinstance(data, list) else [data]
                    for entry in entries:
                        if entry.get("@type") != "MusicEvent":
                            continue
                        # Extract event info
                        event_name = entry.get("name")
                        event_date = entry.get("startDate")
                        venue = entry.get("location", {}).get("name")
                        address = entry.get("location", {}).get("address", {}).get("streetAddress")
                        city = entry.get("location", {}).get("address", {}).get("addressLocality")
                        offers = entry.get("offers")
                        if not offers:
                            continue
                        offers = offers if isinstance(offers, list) else [offers]
                        for offer in offers:
                            if not isinstance(offer, dict):
                                continue
                            availability = offer.get("availability")
                            url = offer.get("url")
                            price = offer.get("price")
                            currency = offer.get("priceCurrency")
                            description = offer.get("description")
                            # Compose details string
                            details_str = f"Event: {event_name} | Date: {event_date} | Venue: {venue}, {address}, {city} | "
                            details_str += f"Availability: {availability} | URL: {url} | Price: {price or 'N/A'} {currency or ''} | Description: {description or 'N/A'}"
                            jsonld_details.append(details_str)
                            if availability == "http://schema.org/InStock":
                                found_in_json = True
                except Exception:
                    continue
            if found_in_json:
                layer_results.append("[Layer 4: JSON-LD] TICKETS POSSIBLY AVAILABLE (InStock offer found)")
                match_layers.append("Layer 4: JSON-LD")
                if jsonld_details:
                    layer_results.extend([f"[Layer 4: JSON-LD] {d}" for d in jsonld_details])
            else:
                layer_results.append("[Layer 4: JSON-LD] NO TICKETS (no matching offers)")
        except Exception as e:
            layer_results.append(f"[Layer 4: JSON-LD] ERROR: {e}")

        # --- Layer 5: ticket-list UI block ---
        try:
            ticket_list = soup.find(attrs={"data-testid": "ticket-list"})
            if ticket_list:
                layer_results.append("[Layer 5: ticket-list UI] TICKETS POSSIBLY AVAILABLE (ticket-list UI found)")
                match_layers.append("Layer 5: ticket-list UI")
            else:
                layer_results.append("[Layer 5: ticket-list UI] NO TICKETS (ticket-list UI not found)")
        except Exception as e:
            layer_results.append(f"[Layer 5: ticket-list UI] ERROR: {e}")

        # Only consider tickets found if Layer 1 (VisuallyHidden) passes (confirmed for Ozzy and Lzzy)
        found = "Layer 1: VisuallyHidden" in match_layers

        with open(log_file, "a") as f:
            f.write(f"[{datetime.now()}] CHECK RESULT: {'FOUND' if found else 'NONE'}\n")
            for line in layer_results:
                f.write(line + "\n")
            if jsonld_details:
                f.write("Details:\n" + "\n".join(jsonld_details) + "\n")
            f.write("-" * 60 + "\n")
        print("Results written to log file.")

        return found, jsonld_details
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
            'timeout': 60000
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
            await asyncio.wait_for(page.reload({'waitUntil': 'networkidle2'}), timeout=60)
            await asyncio.wait_for(page.waitForSelector("script[type='application/ld+json']"), timeout=60)
            html = await page.content()
            found, details = await check_ticket_availability(html, log_file)
            check_count += 1
            if found:
                print("Tickets found! Sending email alert...")
                await send_email_alert(details, log_file)
            else:
                print("No tickets found.")
            print(f"Waiting {CHECK_INTERVAL} seconds...\n")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass  # Normal, just continue loop
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