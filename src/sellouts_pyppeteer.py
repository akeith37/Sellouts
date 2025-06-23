import os
import re
import json
import asyncio
import signal
import smtplib
import shutil
import tempfile
import random
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import warnings
import pyppeteer
from pyppeteer import launch
from pyppeteer_stealth import stealth 


#Suppress Pyppeteer shutdown coroutine warning
pyppeteer.__pyppeteer_await_shutdown__ = False
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine 'Launcher.killChrome' was never awaited")

#Load environment variables from .env file
## .env file needs to be in the same directory as this script
load_dotenv()
EMAIL_ADDRESS=os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD=os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL=os.getenv("RECIPIENT_EMAIL")
CHECK_INTERVAL=60 #seconds between checking again
ozzy_url="https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"
lzzy_url="https://www.ticketmaster.co.uk/halestorm-the-neverest-tour-cardiff-20-11-2025/event/360062978E2B0C80"
TICKET_URL= lzzy_url

# Check for required environment variables
required_env_vars = [EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL]
if not all(required_env_vars):
    raise EnvironmentError("One or more required environment variables (EMAIL_ADDRESS, EMAIL_PASSWORD, RECIPIENT_EMAIL) are missing.")

shutdown_event = asyncio.Event() # Event to signal shutdown
user_data_dir = os.path.join(os.getcwd(), 'user_data') # Set up a persistent user-data directory to keep cookies/session
os.makedirs(user_data_dir, exist_ok=True)

# ---- Email Alert
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
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now()}] EMAIL FAILED TO SEND: {e}\n\n")

# ---- Ticket availability check logic ---- 
async def check_ticket_availability(html_content, log_file, check_count):
    soup = BeautifulSoup(html_content, "html.parser")
    ticket_details = []
    match_layers = []
    layer_results = []

    if check_count == 0:
        print("Checking tickets for the first time.")
    else:
        print(f"Page has been refreshed and checked again {check_count} time(s)")
        
    # 1. Layer 1: Result count span from UI indicator
    try:
        result_span = soup.find('span', class_=lambda c: c and 'resultCount' in c)
        if result_span:
            text = result_span.get_text(strip=True).lower()
            if text.startswith("0 no results"):
                layer_results.append("[Layer 1] resultCount: 0 no results -> NO TICKETS.")
            elif  "result" in text and "no" not in text:
                layer_results.append(f"[Layer 1] resultCount: '{text}' -> MATCH")
                match_layers.append("Layer 1")
        else:
            layer_results.append("[Layer 1] resultCount: span not found")
    except Exception as e:
        layer_results.append(f"[Layer 1] resultCount: error - {e}")
            
    # Layer 2: Sold-Out Banner
    try:
        banner = soup.find('span', {'data-testid': 'message-bar-text'})
        if banner and "no tickets currently available" in banner.get_text(strip=True).lower():
            layer_results.append("[Layer 2] sold-out banner: MATCH -> NO TICKETS")
        else:
            layer_results.append("[Layer 2] sold-out banner: no match")
            match_layers.append("Layer 2 (no sold-out text)")
    except Exception as e:
        layer_results.append(f"[Layer 2] sold-out banner: error - {e}")
            
    # Layer 3: JSON-LD ticket offer
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
                        location = offer.get("name") or offer.get("category") or offer.get("description")
                        if (
                            availability == "http://schema.org/InStock"
                            and isinstance(url, str)
                            and "ticketmaster.co.uk" in url.lower()
                            and "event" in url.lower()
                            and price
                        ):
                            detail = f"- Price: {price or 'Unavailable'} {currency or ''} | Location: {location or 'N/A'}"
                            ticket_details.append(detail)
                            found_in_json = True
            except Exception as e:
                continue
        if found_in_json:
            match_layers.append("Layer 3")
            layer_results.append("[Layer 3] JSON-LD: MATCH")
        else:
            layer_results.append("[Layer 3] JSON-LD: no matching offers")
    except Exception as e:
        layer_results.append(f"[Layer 3] JSON-LD: error - {e}")
    
    # Layer 4: ticket-list UI block
    try:
        ticket_list = soup.find(attrs={"data-testid": "ticket-list"})
        if ticket_list:
            match_layers.append("Layer 4")
            layer_results.append("[Layer 4] ticket-list UI: MATCH")
        else:
            layer_results.append("[Layer 4] ticket-list UI: not found")
    except Exception as e:
        layer_results.append(f"[Layer 4] ticket-list UI: error - {e}")
        
    # Only consider tickets found if Layer 1 passes because its the only one I'm confident in right now
    found = "Layer 1" in match_layers
    
    with open(log_file, "a") as f:
        f.write(f"[{datetime.now()}] CHECK RESULT: {'FOUND' if found else 'NONE'}\n")
        for line in layer_results:
            f.write(line + "\n")
        if ticket_details:
            f.write("Details:\n" + "\n".join(ticket_details) + "\n")
        f.write("-" * 60 + "\n")

    return found, ticket_details

# ---- Check Tickets Loop ----
async def check_tickets_loop(page):
    log_file = "sellouts_log.txt"
    check_count = 0
    while not shutdown_event.is_set():
        try:
            print(f"Checking tickets... (check count: {check_count})")
            await asyncio.wait_for(page.reload({'waitUntil': 'networkidle2'}), timeout=60)
            print("reload complete")
            await asyncio.wait_for(page.waitForSelector("script[type='application/ld+json']"), timeout=60)
            print("waitForSelector complete")
            html = await page.content()
            print("Page content retrieved successfully.")

            with open("html_dump_lzzy", "a") as f:
                f.write(html)
                print("HTML content dumped to html_dump_lzzy")

            found, details = await check_ticket_availability(html, log_file, check_count)
            check_count += 1
            if found:
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
            continue
        except Exception as e:
            import traceback
            print("Unexpected error:", e)
            traceback.print_exc()
            continue

# ---- Shutdown and Cleanup ----
async def shutdown(browser):
    print("Shutting down...")
    if browser:
        await browser.close()
        print("Browser closed.")
    # If you want to clear user data on exit, uncomment the following line:
    # shutil.rmtree(user_data_dir, ignore_errors=True)

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
    try:
        browser = await launch({
            "headless": False,
            "userDataDir": user_data_dir, #Store cookies/session info
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
                get: () => undefined,  // Return `undefined` instead of `true` (headless Chrome) or `false`
                configurable: true     // Configurable to allow deletion or redefinition if needed
            });

            // 2. Spoof `navigator.languages` to a typical user-preferred languages array
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']  // Example languages (US English as primary)
            });

            // 3. Spoof `navigator.platform` to a common platform value
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'  // Pretend to be on Windows 32-bit (common on Windows 10/11)
            });

            // 4. Spoof `navigator.deviceMemory` to a typical memory size in GB
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8  // e.g., 8 GB of device memory
            });

            // 5. Spoof `navigator.hardwareConcurrency` to a typical number of CPU cores
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 4  // e.g., 4 logical processors (common default)
            });

            // 6. Spoof `navigator.plugins` to simulate installed plugins (avoid empty plugins list)
            if (navigator.plugins && navigator.plugins.length === 0) {
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3]  // Return a non-empty dummy array (length > 0 suffices for detection)
                });
            }

            // 7. Canvas fingerprint spoofing: override toDataURL to return a fake image in certain cases
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
                value: function(...args) {
                    const [type, ...rest] = args;
                    // If a script is attempting the known fingerprinting canvas (e.g. 220x30px PNG), return a fake image
                    if (type === 'image/png' && this.width === 220 && this.height === 30) {
                        // Return a consistent fake PNG data URL (here a small blank image) to spoof canvas fingerprint
                        return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAANwAAAAeCAIAAADIGOdpAAAAbElEQVR4nO3SMQEAIAzAMMC/5/FjgB6Jgh7dM7Og5PwOgJcpyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkmJIcU5JjSnJMSY4pyTElOaYkx5TkXOL+AznTluWxAAAAAElFTkSuQmCC';
                    }
                    // Otherwise, fall back to the original toDataURL method
                    return originalToDataURL.apply(this, args);
                }
            });

            // 8. Audio fingerprint spoofing: override AudioBuffer.getChannelData to return altered data
            const originalGetChannelData = AudioBuffer.prototype.getChannelData;
            Object.defineProperty(AudioBuffer.prototype, 'getChannelData', {
                value: function(...args) {
                    const originalBuffer = originalGetChannelData.apply(this, args);
                    // Create a new Float32Array with the same data to avoid modifying the original buffer
                    const newBuffer = new Float32Array(originalBuffer);
                    if (newBuffer.length > 0) {
                        // Slightly modify the first sample in the audio data (inaudible change) to spoof the fingerprint
                        newBuffer[0] += 0.0001;
                    }
                    return newBuffer;
                }
            });
        })();
        """)
        await page.goto(TICKET_URL, {
            'waitUntil': 'networkidle2',
            'timeout': 90000  # Wait up to 90 seconds for the page to load
        })
        await page.waitForSelector("script[type='application/ld+json']")
        await check_tickets_loop(page)
    except Exception as e:
        import traceback
        print("Fatal error in main():", e)
        traceback.print_exc()
    finally:
        await shutdown(browser)
        
if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Exiting gracefully.")
        shutdown_event.set()