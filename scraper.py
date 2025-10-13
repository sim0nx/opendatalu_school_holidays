#!/usr/bin/env python3

"""Scrape school holidays from https://guichet.public.lu and dump them as machine readable JSON."""

import asyncio
import datetime
import json
import logging
import pathlib
import re
import typing

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCRIPT_PATH = pathlib.Path(__file__).resolve().parent
JSON_DUMP_PATH = SCRIPT_PATH / 'school_holidays.json'

BASE_URL = 'https://guichet.public.lu'
SCHOOL_CALENDAR_PATH = 'citoyens/outils/calendrier-scolaire.html'
LANGUAGES = ('lb', 'de', 'fr', 'en')

language_urls = {
  'en': f'{BASE_URL}/en/{SCHOOL_CALENDAR_PATH}',
  # 'lb': f'{BASE_URL}/lb/{SCHOOL_CALENDAR_PATH}',
  'fr': f'{BASE_URL}/fr/{SCHOOL_CALENDAR_PATH}',
  'de': f'{BASE_URL}/de/{SCHOOL_CALENDAR_PATH}',
}

language_description_mappings = {
  'All Saints Day holidays': {'en': 'All Saints Day holidays', 'fr': 'Congé de la Toussaint', 'de': 'Allerheiligenferien', 'lb': 'Allerhellegevakanz'},
  'Saint Nicholas Day': {'en': 'Saint Nicholas Day', 'fr': 'Fête de Saint Nicolas', 'de': 'Nikolaustag', 'lb': 'Niklosdag'},
  'Christmas holidays': {'en': 'Christmas holidays', 'fr': 'Vacances de Noël', 'de': 'Weihnachtsferien', 'lb': 'Chrëschtvakanz'},
  'Carnival holidays': {'en': 'Carnival holidays', 'fr': 'Congé de Carnaval', 'de': 'Karnevalsferien', 'lb': 'Fuesvakanz'},
  'Easter holidays': {'en': 'Easter holidays', 'fr': 'Vacances de Pâques', 'de': 'Osterferien', 'lb': 'Ouschtervakanz'},
  'Public holiday': {'en': 'Public holiday', 'fr': 'Jour férié légal', 'de': 'Gesetzlicher Feiertag', 'lb': 'Schoulfräien Dag'},
  'Public holiday on Europe Day': {
    'en': 'Public holiday on Europe Day',
    'fr': 'Jour férié légal de la Journée de l’Europe',
    'de': 'Gesetzlicher Feiertag am Europa-Tag',
    'lb': 'Feierdag um Europadag',
  },
  'Public holiday on Ascension Day': {
    'en': 'Public holiday on Ascension Day',
    'fr': 'Jour férié légal pour l’Ascension',
    'de': 'Gesetzlicher Feiertag an Christi Himmelfahrt',
    'lb': 'Schoulfräien dag fir Christi Himmelfaart',
  },
  'Pentecost holidays': {'en': 'Pentecost holidays', 'lb': 'Päischtvakanz', 'fr': 'Congé de la pentecôte', 'de': 'Pfingstferien'},
  "Public holiday for the public celebration of HRH the Grand Duke's birthday": {
    'en': "Public holiday for the public celebration of HRH the Grand Duke's birthday",
    'fr': 'Jour de congé pour la célébration publique de l’anniversaire de S.A.R. le Grand-Duc',
    'de': 'Schulfreier Tag aus Anlass der Feierlichkeiten zum Geburtstag S.K.H. des Großherzogs',
    'lb': 'Schoulfräien Dag fir d’Feierlechkeete fir de Gebuertsdag vum S.A.R. de Grand-Duc',
  },
  'Summer holidays': {'en': 'Summer holidays', 'lb': 'Summervakanz', 'fr': 'Vacances d’été', 'de': 'Sommerferien'},
  'Public holiday on Whit Monday': {
    'en': 'Public holiday on Whit Monday',
    'fr': 'Jour férié légal le lundi de Pentecôte',
    'de': 'Gesetzlicher Feiertag am Pfingstmontag',
    'lb': 'Feierdag um Päischtméindeg',
  },
  'Public holiday on Easter Monday': {
    'en': 'Public holiday on Easter Monday',
    'fr': 'Jour férié légal le lundi de Pâques',
    'de': 'Gesetzlicher Feiertag am Ostermontag',
    'lb': 'Feierdag um Ouschterméindeg',
  },
}

# Pattern for holidays like "Saint Nicholas Day: 6 December 2024 (only for pre-primary and primary education levels);"
holiday_pattern = re.compile(r'[\s\w,]+\s+(\d{1,2})(?:\.|er)?\s+(\w+)\s+(\d{4})[\s\w,]+\s+(\d{1,2})(?:\.|er)?\s+(\w+)\s+(\d{4})')

# Alternative pattern for holidays like "Public holiday: Friday 1 May 2026."
alt_holiday_pattern = re.compile(r'([^:]+): (?:[\s\w,]+)?(\d{1,2})(?:\.|er)?\s+(\w+)\s+(\d{4})')

# Month name to number mapping
months = {
  'january': 1,
  'janvier': 1,
  'januar': 1,
  'february': 2,
  'février': 2,
  'februar': 2,
  'march': 3,
  'mars': 3,
  'mäerz': 3,
  'märz': 3,
  'april': 4,
  'avril': 4,
  'abrëll': 4,
  'may': 5,
  'mai': 5,
  'mee': 5,
  'juin': 6,
  'june': 6,
  'juni': 6,
  'july': 7,
  'juillet': 7,
  'juli': 7,
  'august': 8,
  'août': 8,
  'september': 9,
  'septembre': 9,
  'october': 10,
  'octobre': 10,
  'oktober': 10,
  'november': 11,
  'novembre': 11,
  'december': 12,
  'décembre': 12,
  'dezember': 12,
}


def json_encoder_date(obj: typing.Any) -> str:
  if isinstance(obj, datetime.date):
    return obj.isoformat()

  return obj


def parse_date(day: int, month_name: str, year: int) -> datetime.date | None:
  """Convert day, month name, and year to date object."""
  try:
    month_num = months.get(month_name.lower())
    if month_num:
      iso_date = f'{year}-{month_num:02d}-{int(day):02d}'
      return datetime.date.fromisoformat(iso_date)
  except (ValueError, AttributeError):
    pass
  return None


async def scrape_school_holidays_from_website() -> dict | None:
  """Scrape school holidays from the Luxembourg government website."""
  holidays = {}

  for language_key, language_url in language_urls.items():
    try:
      async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(language_url, timeout=30.0)
        response.raise_for_status()

      soup = BeautifulSoup(response.text, 'html.parser')

      page_content = soup.find('div', class_='cmp-accordion')

      for html_tag_details in page_content.find_all('details'):
        for li in html_tag_details.find_all('li'):
          strong_text = li.find('strong').text
          strong_text = f'{strong_text[0].upper()}{strong_text[1:]}'
          li_text = li.get_text()

          if match := holiday_pattern.search(li_text, re.IGNORECASE):
            holiday_name = strong_text
            start_day, start_month, start_year = int(match.group(1)), match.group(2), int(match.group(3))
            end_day, end_month, end_year = int(match.group(4)), match.group(5), int(match.group(6))

            start_date = parse_date(start_day, start_month, start_year)
            end_date = parse_date(end_day, end_month, end_year)

            if start_date and end_date:
              holiday_key = (start_date, end_date)
              if holiday_key not in holidays:
                holidays[holiday_key] = {
                  language_key: holiday_name,
                  'start_date': start_date,
                  'end_date': end_date,
                }
              else:
                holidays[holiday_key][language_key] = holiday_name

          elif match := alt_holiday_pattern.search(li_text, re.IGNORECASE):
            holiday_name = strong_text.strip(':')
            start_day, start_month, start_year = int(match.group(2)), match.group(3), int(match.group(4))
            end_day, end_month, end_year = start_day, start_month, start_year

            start_date = parse_date(start_day, start_month, start_year)
            end_date = parse_date(end_day, end_month, end_year)

            if start_date and end_date:
              holiday_key = (start_date, end_date)
              if holiday_key not in holidays:
                if language_key != 'en':
                  logger.warning('Probably bad data! - %s %s %s %s', language_key, holiday_name, start_date, end_date)
                else:
                  holidays[holiday_key] = {
                    language_key: holiday_name,
                    'start_date': start_date,
                    'end_date': end_date,
                  }
              else:
                holidays[holiday_key][language_key] = holiday_name

    except (OSError, httpx.HTTPError) as e:
      logger.error('Error scraping school holidays from website: %s', e)
      return None

  for _, v in holidays.items():
    for lang in LANGUAGES:
      if lang not in v:
        v[lang] = language_description_mappings[v['en']][lang]

  logger.info('Scraped %s school holidays from website', sum(len(holidays) for holidays in holidays.values()))
  return holidays


async def main() -> None:
  """Main."""
  holidays = await scrape_school_holidays_from_website()
  updated_entries = 0

  if JSON_DUMP_PATH.is_file():
    with JSON_DUMP_PATH.open('r') as fhdl:
      old_data_raw = json.load(fhdl)

    old_data = {}
    for e in old_data_raw:
      old_data[f'{e["start_date"]}_{e["end_date"]}'] = e
  else:
    old_data = {}

  for key_, entry in holidays.items():
    key = f'{key_[0].isoformat()}_{key_[1].isoformat()}'

    if key not in old_data:
      old_data[key] = entry
      updated_entries += 1

  holidays_list = list(old_data.values())

  with JSON_DUMP_PATH.open('w') as fhdl:
    json.dump(holidays_list, fhdl, indent=2, default=json_encoder_date)

  print(f'Updated {updated_entries} entries')


if __name__ == '__main__':
  asyncio.run(main())
