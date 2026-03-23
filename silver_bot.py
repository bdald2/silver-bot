import requests
from bs4 import BeautifulSoup
import os
import re
import hashlib

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8023059821:AAGGn4tcg60mOmRDMC7sI386P2BAzC-LqYk")
CHAT_ID = os.environ.get("CHAT_ID", "8039335944")
MODE = os.environ.get("MODE", "daily")

def get_latest_post():
    """RSS에서 은/실버 관련 최신 글 찾기. 없으면 최신 글 반환."""
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None

    for item in items[:20]:
        title = item.find("title").text.strip()
        if re.search(r'은매입|은판|실버|silver', title, re.IGNORECASE):
            link = item.find("link").text.strip()
            return title, link

    latest = items[0]
    return latest.find("title").text.strip(), latest.find("link").text.strip()

def get_latest_gold_post():
    """RSS에서 금/골드 관련 최신 글 찾기. 없으면 최신 글 반환."""
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None

    for item in items[:20]:
        title = item.find("title").text.strip()
        if re.search(r'금매입|금판|골드|순금|gold', title, re.IGNORECASE):
            link = item.find("link").text.strip()
            return title, link

    latest = items[0]
    return latest.find("title").text.strip(), latest.find("link").text.strip()

def get_post_content(link):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")

    body = (
        post_soup.select_one("div.se-main-container") or
        post_soup.select_one("div#postViewArea") or
        post_soup.select_one("div.post-view") or
        post_soup.select_one("div#content")
    )
    if not body:
        return ""

    raw_lines = body.get_text(separator="\n").split("\n")
    lines = [l.strip() for l in raw_lines if l.strip()]

    silver_lines = []
    capture = False
    for line in lines:
        if re.search(r'은바|실버|은판|silver|은\s*매입', line, re.IGNORECASE):
            capture = True
        if capture and re.search(r'순금|골드바|금바|팔라듐|백금', line, re.IGNORECASE):
            break
        if capture:
            silver_lines.append(line)

    if not silver_lines:
        silver_lines = [l for l in lines if re.search(r'[\d,]+\s*원', l)]

    cleaned = []
    i = 0
    while i < len(silver_lines):
        line = silver_lines[i]
        if re.match(r'^[\d,]+$', line) and i + 1 < len(silver_lines) and re.match(r'^원', silver_lines[i+1]):
            cleaned.append(line + silver_lines[i+1])
            i += 2
        else:
            cleaned.append(line)
            i += 1

    return "\n".join(cleaned[:15]) if cleaned else ""

def get_gold_post_content(link):
    """금 관련 내용 추출"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")

    body = (
        post_soup.select_one("div.se-main-container") or
        post_soup.select_one("div#postViewArea") or
        post_soup.select_one("div.post-view") or
        post_soup.select_one("div#content")
    )
    if not body:
        return ""

    raw_lines = body.get_text(separator="\n").split("\n")
    lines = [l.strip() for l in raw_lines if l.strip()]

    gold_lines = []
    capture = False
    for line in lines:
        if re.search(r'순금|골드바|금바|금\s*매입|금판|골드', line, re.IGNORECASE):
            capture = True
        if capture and re.search(r'은바|실버|은판|팔라듐|백금', line, re.IGNORECASE):
            break
        if capture:
            gold_lines.append(line)

    if not gold_lines:
        gold_lines = [l for l in lines if re.search(r'[\d,]+\s*원', l)]

    cleaned = []
    i = 0
    while i < len(gold_lines):
        line = gold_lines[i]
        if re.match(r'^[\d,]+$', line) and i + 1 < len(gold_lines) and re.match(r'^원', gold_lines[i+1]):
            cleaned.append(line + gold_lines[i+1])
            i += 2
        else:
            cleaned.append(line)
            i += 1

    return "\n".join(cleaned[:15]) if cleaned else ""

def extract_prices(content):
    prices = re.findall(r'[\d,]+원', content)
    return "|".join(prices)

def get_price_hash(content):
    prices = extract_prices(content)
    return hashlib.md5(prices.encode()).hexdigest()

def build_message(title, link, content, prefix="📊 은 시세"):
    if content:
        return f"{prefix}\n\n{title}\n\n{content}\n\n🔗 {link}"
    return f"{prefix}\n\n{title}\n\n🔗 {link}"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)

def load_last_hash(filename="last_post.txt"):
    try:
        with open(filename, "r") as f:
            return f.read().strip()
    except:
        return ""

def save_last_hash(price_hash, filename="last_post.txt"):
    with open(filename, "w") as f:
        f.write(price_hash)

if __name__ == "__main__":
    if MODE in ("daily", "check"):
        title, link = get_latest_post()
        if not link:
            print("은 게시글을 찾을 수 없습니다.")
        elif MODE == "daily":
            content = get_post_content(link)
            msg = build_message(title, link, content, prefix="📊 [매일 11시] 은 최신 시세")
            send_telegram(msg)
            print(msg)
        elif MODE == "check":
            content = get_post_content(link)
            current_hash = get_price_hash(content)
            last_hash = load_last_hash("last_silver_post.txt")
            if current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🆕 은 시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_silver_post.txt")
                print(f"은 시세 변경 감지: {title}")
            else:
                print("은 시세 변경 없음")

    if MODE in ("gold_daily", "gold_check"):
        title, link = get_latest_gold_post()
        if not link:
            print("금 게시글을 찾을 수 없습니다.")
        elif MODE == "gold_daily":
            content = get_gold_post_content(link)
            msg = build_message(title, link, content, prefix="📊 [매일 11시] 금 최신 시세")
            send_telegram(msg)
            print(msg)
        elif MODE == "gold_check":
            content = get_gold_post_content(link)
            current_hash = get_price_hash(content)
            last_hash = load_last_hash("last_gold_post.txt")
            if current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🆕 금 시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_gold_post.txt")
                print(f"금 시세 변경 감지: {title}")
            else:
                print("금 시세 변경 없음")
