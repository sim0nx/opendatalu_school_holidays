#!/usr/bin/env python3

"""Scrape a fresh copy of the data and upload it to data.public.lu."""

import asyncio
import io
import json
import logging
import pathlib

import httpx2
import yaml

import scraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCRIPT_PATH = pathlib.Path(__file__).resolve().parent
JSON_DUMP_PATH = SCRIPT_PATH / 'school_holidays.json'
CONFIG_PATH = SCRIPT_PATH / 'config.yaml'


async def main() -> None:
  with CONFIG_PATH.open() as fhdl:
    config = yaml.safe_load(fhdl)

  api_url = config['api_url']
  api_key = config['api_key']
  dataset_id = config['dataset_id']
  resource_id = config['resource_id']

  holidays, updated_entries = await scraper.get_update_data(update_data=False, discard_old_data=True)
  holidays_dump = json.dumps(holidays, indent=4, default=scraper.json_encoder_date)
  holidays_dump_bio = io.BytesIO(holidays_dump.encode('utf-8'))

  client = httpx2.AsyncClient(headers={'X-API-KEY': api_key}, timeout=10)

  upload_url = f'{api_url}/datasets/{dataset_id}/resources/{resource_id}/upload/'

  files = {'file': ('school-holidays.json', holidays_dump_bio, 'text/plain')}

  res = await client.post(upload_url, files=files)
  res.raise_for_status()


if __name__ == '__main__':
  asyncio.run(main())
