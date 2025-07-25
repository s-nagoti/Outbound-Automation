"""
Outbound Vapi.ai Caller Script

Automates outbound calls using the Vapi.ai API, reading phone numbers and dynamic data from a CSV file.

USAGE:
    python outbound_vapi_caller.py --csv_file path/to/numbers.csv

CONFIGURATION:
    Set the following variables at the top of this file before running:
        VAPI_API_KEY           - Your Vapi API Secret Key
        VAPI_PHONE_NUMBER_ID   - The ID of the Vapi phone number to call from
        VAPI_WORKFLOW_ID       - The ID of the Vapi Workflow to use for the calls
        MAX_CONCURRENT_CALLS   - (Optional) Max simultaneous calls (default: 10)

CSV FORMAT:
    Must include a 'phone_number' column (E.164 format). All other columns are passed as dynamic variables.

Example:
    phone_number,customer_name,company
    +15551234567,Alice Smith,Company1
    ...
"""

# --- CONFIGURATION: Set these values before running ---
VAPI_API_KEY = "563b8bbe-3f68-4fd5-95d4-2f431d3c4808"
VAPI_PHONE_NUMBER_ID = "6f60cf66-98c8-4e4b-bf5c-f3eb971e9cc6"
VAPI_WORKFLOW_ID = "54837a4f-5fe9-4ef1-9fbb-835c6ce5aee2"
MAX_CONCURRENT_CALLS = 5  # Or any integer you want
# -----------------------------------------------------

import sys
import csv
import argparse
import asyncio
import logging
from typing import Dict, List, Any
import aiohttp
import requests

# --- Configuration Loading ---
def load_config() -> Dict[str, Any]:
    """Load configuration from variables set at the top of the file."""
    config = {
        'VAPI_API_KEY': VAPI_API_KEY,
        'VAPI_PHONE_NUMBER_ID': VAPI_PHONE_NUMBER_ID,
        'VAPI_WORKFLOW_ID': VAPI_WORKFLOW_ID,
        'MAX_CONCURRENT_CALLS': MAX_CONCURRENT_CALLS,
    }
    missing = [k for k, v in config.items() if not v and k != 'MAX_CONCURRENT_CALLS']
    if missing:
        sys.exit(f"Missing required configuration values: {', '.join(missing)}. Please set them at the top of the script.")
    return config

# --- Logging Setup ---
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

# --- Vapi API Credential Check ---
def check_vapi_credentials(api_key: str) -> None:
    """Check Vapi API key validity by making a GET /account request."""
    url = 'https://api.vapi.ai/account'
    headers = {'Authorization': f'Bearer {api_key}'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 401:
            logging.error('Vapi API key is invalid (401 Unauthorized).')
            sys.exit(1)
        elif resp.status_code != 200:
            logging.error(f'Vapi account check failed: {resp.status_code} {resp.text}')
            sys.exit(1)
        logging.info('Vapi API key validated successfully.')
    except requests.RequestException as e:
        logging.error(f'Error checking Vapi credentials: {e}')
        sys.exit(1)

# --- CSV Reading ---
def read_csv(csv_file: str) -> List[Dict[str, str]]:
    """Read CSV and return list of row dicts."""
    with open(csv_file, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        print("DEBUG: CSV headers found:", reader.fieldnames)
        if 'phone_number' not in reader.fieldnames:
            logging.error("CSV must contain a 'phone_number' column.")
            sys.exit(1)
        rows = [row for row in reader]
    return rows

# --- Vapi Call Function ---
async def make_vapi_call(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, config: Dict[str, Any], row: Dict[str, str], results: Dict[str, Any]):
    phone_number = row.get('phone_number')
    customer_data = {k: v for k, v in row.items() if k != 'phone_number'}
    url = 'https://api.vapi.ai/call'
    headers = {
        'Authorization': f"Bearer {config['VAPI_API_KEY']}",
        'Content-Type': 'application/json',
    }
    payload = {
        'phoneNumberId': config['VAPI_PHONE_NUMBER_ID'],
        'workflowId': config['VAPI_WORKFLOW_ID'],
        'number': phone_number,
        'customer': customer_data,
    }
    async with semaphore:
        try:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                text = await resp.text()
                if resp.status < 200 or resp.status >= 300:
                    logging.error(f"Call failed for {phone_number}: {resp.status} {text}")
                    results['failed'].append({'phone_number': phone_number, 'error': f"{resp.status} {text}"})
                    return
                data = await resp.json()
                call_id = data.get('callId')
                logging.info(f"Call initiated for {phone_number} (callId={call_id})")
                results['success'].append({'phone_number': phone_number, 'callId': call_id})
        except aiohttp.ClientError as e:
            logging.error(f"Network error for {phone_number}: {e}")
            results['failed'].append({'phone_number': phone_number, 'error': str(e)})
        except asyncio.TimeoutError:
            logging.error(f"Timeout for {phone_number}")
            results['failed'].append({'phone_number': phone_number, 'error': 'Timeout'})
        except Exception as e:
            logging.error(f"Unexpected error for {phone_number}: {e}")
            results['failed'].append({'phone_number': phone_number, 'error': str(e)})

# --- Main Async Execution ---
async def process_calls(rows: List[Dict[str, str]], config: Dict[str, Any]):
    semaphore = asyncio.Semaphore(config['MAX_CONCURRENT_CALLS'])
    results = {'success': [], 'failed': []}
    async with aiohttp.ClientSession() as session:
        tasks = [
            make_vapi_call(session, semaphore, config, row, results)
            for row in rows
        ]
        await asyncio.gather(*tasks)
    return results

# --- Summary Report ---
def print_summary(total: int, results: Dict[str, Any]):
    print("\n--- Summary Report ---")
    print(f"Total numbers processed: {total}")
    print(f"Successfully initiated calls: {len(results['success'])}")
    print(f"Failed calls: {len(results['failed'])}")
    if results['failed']:
        print("\nFailed Numbers:")
        for fail in results['failed']:
            print(f"  {fail['phone_number']}: {fail['error']}")

# --- Main Entrypoint ---
def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Automate outbound calls using Vapi.ai API.")
    parser.add_argument('--csv_file', required=True, help='Path to input CSV file')
    args = parser.parse_args()

    config = load_config()
    # check_vapi_credentials(config['VAPI_API_KEY'])
    rows = read_csv(args.csv_file)
    if not rows:
        logging.error('No rows found in CSV.')
        sys.exit(1)
    logging.info(f"Loaded {len(rows)} rows from CSV.")

    try:
        results = asyncio.run(process_calls(rows, config))
    except KeyboardInterrupt:
        logging.warning('Interrupted by user.')
        sys.exit(1)
    print_summary(len(rows), results)

if __name__ == "__main__":
    main() 