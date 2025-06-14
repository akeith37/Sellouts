import os
import re
import json
import asyncio
import signal
import smtplib
import shutil
import tempfile
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import warnings
from pyppeteer import launch
import pyppeteer


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
TICKET_URL="https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"
#LZZY#"https://www.ticketmaster.co.uk/halestorm-glasgow-21-11-2025/event/3600628EEF705D6B"
#BS#"https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"

#Set temp profle for browser state
shutdown_event = asyncio.Event()
temp_user_data_dir = tempfile.mkdtemp() #Create temporary user data directory

# ---- Email Alert
async def send_email_alert(details, logfile):
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
async def check_ticket_availability(html_content):
    soup = BeautifulSoup(html_content,"html.parser")
    ticket_detils = []
    match_layers = []
    layer_results = []
        
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
        later_results.append(f"[Layer 1] resultCount: error - {e}")
            
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
        scripts = soup.findall("script", type="application/ld+json")
        found_in_json = False
        for script in scripts:
            try:
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
            except:
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
        
    found = bool(match_layers)
    
    with open(log_file, "a") as f:
        f.write(f"[{datetime.now()}] CHECK RESULT: {'FOUND' if found else 'NONE'}\n")
        for line in layer_results:
            f.write(line + "\n")
        if ticket_details:
            f.write("Details:\n" + "\n".join(ticket_details) + "\n")
        f.write("-" * 60 + "\n")
        
    return found, ticket_details

# ---- Check Tickets Loop ----
async def check_tickets_loop(browser, page):
    log_file = "sellouts_log.txt"
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(page.reload({'waitUntil': 'networkidle2'}), timeout=30)
            await asyncio.wait_for(page.waitForSelector("script[type='application/ld+json']"), timeout=10)
            html = await page.content()
            found, details = await check_ticket_availability(html, log_file)
            if found:
                await send_email_alert(details, log_file)
                break # i dont think i want this, probably stops the program once found
            else:
                print("No tickets found.")
        except asyncio.TimeoutError:
            print("Timed out waiting for page load or selector.")
        except Exception as e:
            print("Unexpected error:", e)
        print(f"Waiting {CHECK_INTERVAL} seconds...\n")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            continue
        
# ---- Shutdown and Cleanup ----
async def shutdown(browser):
    print("Shutting down...")
    try:
        if browser:
            await browser.close()
            print("Browser clsoed.")
    finally:
        shutil.rmtree(temp_user_data_dir, ignore_errors=True)
        
# ---- Entry Point ----
async def main():
    browser = await launch({
        "headless": False,
        "userDataDir": temp_user_data_dir, #Store cookies/session info
        "args": [
                "--start-maximied",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ],
        "executablePath": "/usr/bin/chromium"
    })
    page = (await browser.pages())[0]
#     await page.set_viewport_size({"width": 1280, "height": 800})
    await page.setExtraHTTPHeaders({
        "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36"
    })
    await page.goto(TICKET_URL, {'waitUntil': 'networkidle2'})
    print("Check broswer for CAPTCHA. Verify that you exist, wait for the next page to load, hit ENTER in the terminal to collect the HTML content")
    input()
    await page.waitForSelector("script[type='application/ld+json']")
    
    def handle_signal(sig, frame):
        print(f"Signal {sig} received. Shutdown requested...")
        shutdown_event.set()
        
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        await check_tickets_loop(browser, page)
    finally:
        await shutdown(browser)
        
if __name__ == "__main__":
    asyncio.run(main())