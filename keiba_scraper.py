import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import time
import random
import re

# スクレイピング間隔の定数 (秒)
SCRAPE_DELAY_SECONDS = 1.0 

# URLを正規化するヘルパー関数
def _normalize_url(url_string):
    if not isinstance(url_string, str):
        return None
    url_string = url_string.strip()
    parsed_url = urlparse(url_string)
    if not parsed_url.scheme and parsed_url.netloc:
        return urlunparse(parsed_url._replace(scheme='https'))
    elif parsed_url.path.startswith('//') and not parsed_url.netloc:
        return 'https:' + parsed_url.path
    elif parsed_url.path.startswith('/https://'):
        return 'https:' + parsed_url.path[1:]
    else:
        return url_string

# scrape_page 関数
def scrape_page(url):
    # User-Agentを一般的な最新のブラウザのものに更新
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36', # 最新に近いChromeのUser-Agent
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'no-cache',
    }
    try:
        normalized_url = _normalize_url(url)
        if not normalized_url:
            return None

        response = requests.get(normalized_url, headers=headers, timeout=20) # タイムアウトを20秒に延長
        response.raise_for_status() 
        
        time.sleep(random.uniform(SCRAPE_DELAY_SECONDS, SCRAPE_DELAY_SECONDS + 0.5)) # ランダムな遅延
        return BeautifulSoup(response.text, 'html.parser')
    
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: scrape_page - HTTP Error occurred ({normalized_url}): {e.response.status_code} - {e.response.reason}")
        error_body_snippet_cleaned = e.response.text[:500].replace('\n', ' ').replace('\r', '').strip()
        print(f"ERROR: scrape_page - Response body (first 500 chars): {error_body_snippet_cleaned}...")
        return None
    except requests.exceptions.RequestException as e:
        print(f"ERROR: scrape_page - General Request Error occurred ({normalized_url}): {e}")
        return None
    except Exception as e:
        print(f"ERROR: scrape_page - Unknown Error occurred in scrape_page: {e}")
        return None

# get_schedule_races 関数
def get_schedule_races(year, month):
    url = f"https://sports.yahoo.co.jp/keiba/schedule/monthly?year={year}&month={month}"
    soup = scrape_page(url)
    if not soup:
        return []

    races = []
    schedule_table = soup.select_one('table#schedule')
    if not schedule_table:
        return []

    current_date = ""
    current_venue_full_text = ""

    for row in schedule_table.select('tbody tr'):
        date_venue_cell = row.find('td', class_='hr-tableSchedule__data--date')
        if date_venue_cell:
            current_date = date_venue_cell.get_text(strip=True).split('（')[0]
            date_p_tag = date_venue_cell.select_one('p')
            if date_p_tag:
                venue_a_tag = date_p_tag.select_one('a')
                if venue_a_tag:
                    current_venue_full_text = venue_a_tag.get_text(strip=True)
                else:
                    venue_text_raw = date_p_tag.get_text(strip=True)
                    match_venue = re.search(r'\d{4}\.\d{2}\.\d{2}（.）\s*(.+)', venue_text_raw)
                    if match_venue:
                        current_venue_full_text = match_venue.group(1).strip()
                    else:
                        current_venue_full_text = "開催場所不明"
        
        race_link_element = row.select_one('a.hr-tableSchedule__link')
        if race_link_element and 'href' in race_link_element.attrs:
            race_name_element = race_link_element.select_one('span.hr-tableSchedule__title')
            race_name = race_name_element.get_text(strip=True) if race_name_element else "レース名不明"
            
            grade_element = race_link_element.select_one('span.hr-label')
            if grade_element:
                race_name += f" {grade_element.get_text(strip=True)}"

            race_url = urljoin(url, race_link_element['href'])
            
            races.append({
                '日付': current_date,
                '開催競馬場': current_venue_full_text,
                'レース名': race_name,
                'URL': race_url
            })
    return races


# get_daily_race_urls 関数
def get_daily_race_urls(main_race_url):
    if not main_race_url or not isinstance(main_race_url, str):
        return []
    try:
        parsed_main_url = urlparse(main_race_url)
        path_segments = parsed_main_url.path.split('/')
        if not path_segments:
            return []
        
        race_code_with_number = path_segments[-1]
        if not race_code_with_number or len(race_code_with_number) < 2 or not race_code_with_number[-2:].isdigit():
            return []
            
        base_code = race_code_with_number[:-2]
        base_path = urlunparse(parsed_main_url._replace(path="/".join(path_segments[:-1])))

        generated_urls = []
        for i in range(1, 13): # 1レースから12レースまで
            race_number_str = str(i).zfill(2)
            full_race_code = base_code + race_number_str
            full_url = f"{base_path}/{full_race_code}"
            generated_urls.append({
                'レース番号': f"{i}R",
                'URL': full_url
            })
        return generated_urls
    except Exception as e:
        print(f"ERROR: get_daily_race_urls - An unexpected error occurred: {e}")
        return []


# get_race_name 関数
def get_race_name(race_url):
    soup = scrape_page(race_url)
    if not soup:
        return "レース名取得エラー"

    race_name_tag = soup.select_one('h2.hr-predictRaceInfo__title')
    if not race_name_tag:
        return "レース名不明"
    
    race_name = race_name_tag.get_text(strip=True)
    return race_name


# scrape_yahoo_keiba_odds 関数
def scrape_yahoo_keiba_odds(url):
    try:
        soup = scrape_page(url)
        if not soup:
            return []

        horse_data = []
        odds_table = soup.select_one('table.hr-tableValue')
        if not odds_table:
            return []

        rows = odds_table.select('tbody.target_modules tr.hr-tableValue__row')
        if not rows:
            return []

        for i, row in enumerate(rows):
            horse_info = {}
            cols = row.select('td.hr-tableValue__data')

            if len(cols) >= 5: # 最低限必要なカラム数があるか確認
                horse_info['馬番'] = cols[1].get_text(strip=True) if len(cols) > 1 and cols[1] else "N/A_馬番"
                horse_name_element = cols[2].select_one('a')
                horse_info['馬名'] = horse_name_element.get_text(strip=True) if len(cols) > 2 and horse_name_element else "N/A_馬名"

                tansho_odds_element = cols[3].select_one('span')
                if not tansho_odds_element:
                    tansho_odds_element = cols[3]
                odds_text = tansho_odds_element.get_text(strip=True)
                try:
                    horse_info['単勝オッズ'] = float(odds_text)
                except ValueError:
                    horse_info['単勝オッズ'] = odds_text

                fukusho_odds_element = cols[4]
                fukusho_text = fukusho_odds_element.get_text(strip=True) if len(cols) > 4 and fukusho_odds_element else "N/A_複勝"
                horse_info['複勝オッズ'] = fukusho_text

                if horse_info['馬番'] != "N/A_馬番":
                    horse_data.append(horse_info)
        return horse_data

    except Exception as e:
        print(f"ERROR: scrape_yahoo_keiba_odds - An unexpected error occurred during odds parsing ({url}): {e}")
        return []