import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from pyppeteer import launch
import pyppeteer
pyppeteer.__pyppeteer_await_shutdown__ = False
from dotenv import load_dotenv
import re
import json
import tempfile
import shutil
import signal
import warnings
from datetime import datetime

#Suppress Pyppeteer shutdown coroutine warning
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine 'Launcher.killChrome' was never awaited")

#Load environment variables from .env file
## .env file needs to be in the same directory as this script
load_dotenv()

EMAIL_ADDRESS=os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD=os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL=os.getenv("RECIPIENT_EMAIL")

CHECK_INTERVAL=60 #seconds between checking again
TICKET_URL="https://www.ticketmaster.ie/sam-fender-belfast-28-08-2025/event/3800618BEE4B0A79"
#LZZY#"https://www.ticketmaster.co.uk/halestorm-glasgow-21-11-2025/event/3600628EEF705D6B"
#BS#"https://www.ticketmaster.co.uk/back-to-the-beginning-birmingham-05-07-2025/event/360062289EF011A5"

#Set runtime state and user data
shutdown_event = asyncio.Event()  #not in last code
temp_user_data_dir = tempfile.mkdtemp() #Create temporary user data directory   #not in last code

#Check if the HTML page content includes ticket availability using JSON-LD
##HTML structure determining ticket availability has been tested with Ticketmaster only
async def tickets_available(page_content):
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for tickets...")
        
        #Extract all <script type="application/ld\\+json">(.*?)</script> blocks
        scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page_content, re.DOTALL)
        found = False
        ticket_details = []
        
        for block in scripts:
            try:
                data = json.loads(block)
                items = data if isinstance(data, list) else [data]
                
                for entry in items:
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
                            and url and isinstance(url, str)
                            and "ticketmaster.co.uk" in url.lower()
                            and (price or currency)
                        ):
                            found = True
                            detail = f"- Price: {price} {currency if currency else ''} | Location: {location if location else 'N/A'}"
                            ticket_details.append(detail)
                            print("Ticket found:")
                            print(detail)
                            print(f" URL: {url}")
            except Exception:
                continue
            
        return found, ticket_details
    except Exception as e:
        print("Error checking ticket availability:", e)
        return False, []
        
#Send and email notification if tickets are found
##email credentials are in .env file
def send_email_alert(details):
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
    except Exception as e:
        print("Failed to send email:", e)
        
#Launch the browser and open the event page
async def init_browser():
    browser = await launch({
        "headless": False,
        "userDataDir": temp_user_data_dir, #Store cookies/session info
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        "executablePath": "/usr/bin/chromium"
    })
    pages = await browser.pages()
    page = pages[0]
    await page.setExtraHTTPHeaders({
        "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.37"
    })
    await page.goto(TICKET_URL, {'waitUntil': 'networkidle2'})
    print("Check browser for CAPTCHA. Verify that you exist, wait for the next page to load, hit ENTER in the terminal to collect the HTML content")
    input()
    await page.waitForSelector("script[type='application/ld+json']")
    return browser, page
    
#Repeatedly reload the same page and check ticket status
async def check_tickets_loop(browser, page, shutdown_event):
    while not shutdown_event.is_set():
        try:
            print("Reloading page...")
            await asyncio.wait_for(page.reload({'waitUntil': 'networkidle2'}), timeout=30)
            await asyncio.wait_for(page.waitForSelector("script[type='application/ld+json']"), timeout=10)
            html = await page.content()
            
#             with open('fender_html.txt', 'w') as html_data:
#                 html_data.writelines(html)
            
            found, details = await tickets_available(html)
            if found:
                print("Tickets found!")
                send_email_alert(details)
                break
            else:
                print("No tickets found yet.")
        except asyncio.CancelledError:
            print("Check loop cancelled")
            break
        except asyncio.TimeoutError:
            print("Timed out waiting for page to load or selector")
        except Exception as e:
            if "Target.detachFromTarget" in str(e):
                print("Session was detached. Rebinding to available tab...")
                pages = await browser.pages()
                if pages:
                    page = pages[0]
                else:
                    print("No open tabs found. Exiting.")
                    break
            else:
                print("Error during check:", e)
                
        print(f"Waiting {CHECK_INTERVAL // 60} minute(s) before checking again.\n")
        done, _ = await asyncio.wait([shutdown_event.wait()], timeout=CHECK_INTERVAL)
        if shutdown_event.is_set():
            break
        
        
async def shutdown(browser):
    print("\nSafely shutting down now...")
    try:
        if browser:
            await browser.close()
            print("Browser closed cleanly.")
    except Exception as e:
        print("Error closing browser:", e)
    finally:
        shutil.rmtree(temp_user_data_dir, ignore_errors=True)
                
                
async def main():
    browser, page = await init_browser()
    shutdown_event = asyncio.Event()
    
    def handle_signal(sig, frame):
        print(f"Signal {sig} received. Shutdown requested...")
        shutdown_event.set()
        
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        await check_tickets_loop(browser, page, shutdown_event)
    finally:
        await shutdown(browser)

if __name__ == "__main__":
    asyncio.run(main())
