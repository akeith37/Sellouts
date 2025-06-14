import requests
import csv
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TM_API_KEY")
BASE_URL = 'https://app.ticketmaster.com/discovery/v2/events.json'

#Status that could mean sold out
UNAVAILABLE_STATUSES = {'offsale', 'soldout', 'canceled', 'postponed', 'rescheduled'}

def get_sold_out_concerts(country_code='GB', size=100, pages=10):
    sold_out = []
    skipped_statuses = set()
    now = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    
    for page in range(pages):
        params = {
            'apikey': API_KEY,
            'countryCode': country_code,
            'classificationName': 'music',
#             'status': 'offsale', #thes are events that TM are no longer selling, could be sold out, past events or sold through partner. date param takes care of past events, need to take case of sold through partner
            'startDateTime': now,
            'size': size,
            'page': page
        }
        
        print(f"Fetching page {page}...")
        response = requests.get(BASE_URL, params=params)
        if response.status_code != 200:
            print(f"Error: {response.status_code}: {response.text}")
            break
        
        data = response.json()
        events = data.get('_embedded', {}).get('events', [])
        for event in events:
            status = event.get('dates', {}).get('status', {}).get('code', 'unknown')
            url = event.get('url')
            
            #Skip if status is not one that would align with being sold out
            if (status is None or status.lower() not in UNAVAILABLE_STATUSES):
                skipped_statuses.add(status)
                continue
            #Skip if not sold on ticketmaster
            if not url or 'ticketmaster' not in url:
                continue
            #Skip if public sale hasnt started yet
            sales_start_str = event.get('sales', {}).get('public', {}).get('startDateTime')
            if sales_start_str:
                sales_start = datetime.fromisoformat(sales_start_str.replace('Z', '+00:00'))
                if sales_start > datetime.now(timezone.utc):
                    continue
            
            name = event.get('name')
            venue = event.get('_embedded', {}).get('venues', [{}])[0].get('name', 'Unknown Venue')
            date = event.get('dates', {}).get('start', {}).get('localDate', 'Unknown Date')
            sold_out.append([name, date, venue, url])

    return sold_out

def save_to_csv(events, filename='sold_out_concerts.csv'):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Event Name', 'Date', 'Venue', 'URL'])
        writer.writerows(events)
    print(f"\nSaved {len(events)} events to {filename}")
    
if __name__ == "__main__":
    events = get_sold_out_concerts()
    save_to_csv(events)