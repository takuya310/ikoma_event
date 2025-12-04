import requests
from bs4 import BeautifulSoup
import csv
import time
from datetime import datetime
from urllib.parse import urljoin
import re

# 設定
BASE_LIST_URL = "https://www.city.ikoma.lg.jp/event2/event_list.php"
OUTPUT_FILE = "events.csv"
HEADERS = ["開催日", "開催時間", "イベント名", "開催場所", "開催場所の住所", "定員", "費用", "持ち物", "申し込み方法", "イベントページURL"]

# 取得する月数
MONTHS_TO_SCRAPE = 3

# セッション作成
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

def get_event_details(detail_url):
    """
    詳細ページから追加情報を取得する関数
    """
    try:
        response = session.get(detail_url)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')

        details = {
            "address": "",
            "capacity": "",
            "cost": "",
            "items": "",
            "apply": ""
        }

        # 詳細ページはテーブル構造の可能性が高いため、th/tdのペア探索を維持
        table_rows = soup.find_all('tr')
        for tr in table_rows:
            th = tr.find('th')
            td = tr.find('td')
            if th and td:
                header_text = th.get_text(strip=True)
                content_text = td.get_text(strip=True)

                if "場所" in header_text or "会場" in header_text:
                    details["address"] = content_text
                elif "定員" in header_text:
                    details["capacity"] = content_text
                elif "費用" in header_text or "参加費" in header_text:
                    details["cost"] = content_text
                elif "持ち物" in header_text:
                    details["items"] = content_text
                elif "申込" in header_text:
                    details["apply"] = content_text

        return details
    except Exception as e:
        print(f"  [Error] 詳細取得エラー ({detail_url}): {e}")
        return {}

def clean_date(text):
    """
    テキストから日付らしい部分を抽出して整形する
    YYYY/MM/DD形式を目指す
    """
    # 年月日抽出の正規表現 (例: 2025年12月1日, 2025/12/1)
    match = re.search(r'(\d{4})[年/](\d{1,2})[月/](\d{1,2})', text)
    if match:
        y, m, d = match.groups()
        return f"{y}/{int(m):02d}/{int(d):02d}"
    
    # 年がない場合 (例: 12月1日, 12/1) -> 現在処理中の年を補完したいが、ここではそのまま返す
    match_short = re.search(r'(\d{1,2})[月/](\d{1,2})', text)
    if match_short:
        m, d = match_short.groups()
        return f"{int(m):02d}/{int(d):02d}"
        
    return None

def scrape_events():
    all_events = []
    today = datetime.now()
    
    print("スクレイピングを開始します...")

    for i in range(MONTHS_TO_SCRAPE):
        target_year = today.year
        target_month = today.month + i
        
        while target_month > 12:
            target_month -= 12
            target_year += 1
            
        current_yyyymm = f"{target_year}{target_month:02d}"
        print(f"--- {target_year}年{target_month}月 (mon={current_yyyymm}) のデータを取得中 ---")

        page = 1
        has_next_page = True

        while has_next_page:
            params = {
                'ev': 2,
                'mon': current_yyyymm,
                'ca': 0,
                'eoeload': 't',
                'page': page
            }
            
            try:
                response = session.get(BASE_LIST_URL, params=params)
                response.encoding = response.apparent_encoding
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # <ul class="event_list"> を取得
                event_list_ul = soup.find('ul', class_='event_list')
                
                if not event_list_ul:
                    # イベントリストが見つからない場合、この月はイベントなしか構造違いの可能性
                    # 最初のページでなければ単にページ切れと判断
                    if page == 1:
                        print(f"  Page {page}: <ul class='event_list'> が見つかりませんでした。")
                    has_next_page = False
                    continue

                event_items = event_list_ul.find_all('li')
                valid_items_in_page = 0

                for li in event_items:
                    try:
                        # 1. タイトルとURLの取得 (<a>タグ)
                        link_tag = li.find('a')
                        if not link_tag:
                            continue
                            
                        title = link_tag.get_text(strip=True)
                        href = link_tag['href']
                        full_url = urljoin(BASE_LIST_URL, href)

                        # 2. 日付の取得 (<p>タグを走査)
                        date_str = ""
                        p_tags = li.find_all('p')
                        
                        # まず「開催」や「期間」が含まれるpタグを探す
                        for p in p_tags:
                            text = p.get_text(strip=True)
                            if "開催" in text or "期間" in text or "日時" in text:
                                extracted_date = clean_date(text)
                                if extracted_date:
                                    date_str = extracted_date
                                    break
                        
                        # キーワードで見つからなければ、日付パターンが含まれる最初のpタグを採用
                        if not date_str:
                            for p in p_tags:
                                extracted_date = clean_date(p.get_text(strip=True))
                                if extracted_date:
                                    date_str = extracted_date
                                    break
                        
                        # それでも日付が取れない場合、スキップするか、デフォルト値を入れるか
                        if not date_str:
                            # ログを出してスキップ
                            # print(f"  [Skip] 日付が見つかりませんでした: {title}")
                            continue

                        # 年が抜けている場合（MM/DDのみ）の補完
                        if len(date_str.split('/')) == 2:
                            date_str = f"{target_year}/{date_str}"

                        # 3. 詳細情報の取得
                        time.sleep(1) # サーバー負荷軽減
                        details = get_event_details(full_url)

                        event_data = {
                            "開催日": date_str,
                            "開催時間": "", # 詳細ページなどから取れれば更新したい
                            "イベント名": title,
                            "開催場所": "", # 詳細ページなどから取れれば更新したい
                            "開催場所の住所": details.get("address", ""),
                            "定員": details.get("capacity", ""),
                            "費用": details.get("cost", ""),
                            "持ち物": details.get("items", ""),
                            "申し込み方法": details.get("apply", ""),
                            "イベントページURL": full_url
                        }
                        
                        # 重複排除 (URLと日付で判定)
                        is_duplicate = False
                        for e in all_events:
                             if e["イベントページURL"] == full_url and e["開催日"] == date_str:
                                 is_duplicate = True
                                 break
                        
                        if not is_duplicate:
                            all_events.append(event_data)
                            valid_items_in_page += 1

                    except Exception as e:
                        print(f"  [Warning] 要素の解析エラー: {e}")
                        continue

                print(f"  Page {page}: {valid_items_in_page} events found.")
                
                # ページ送り判定
                if valid_items_in_page == 0 or page > 10:
                    has_next_page = False
                else:
                    page += 1
                    time.sleep(1)
            
            except Exception as e:
                print(f"  [Error] リクエストエラー (Page {page}): {e}")
                has_next_page = False

    # CSV書き出し
    if all_events:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(all_events)
        print(f"\n完了: 合計 {len(all_events)} 件のイベントを {OUTPUT_FILE} に保存しました。")
    else:
        print("\n警告: イベントが見つかりませんでした。")

if __name__ == "__main__":
    scrape_events()