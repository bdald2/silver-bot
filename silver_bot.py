import requests
from bs4 import BeautifulSoup
import os
import re
import hashlib

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8023059821:AAGGn4tcg60mOmRDMC7sI386P2BAzC-LqYk")
CHAT_ID = os.environ.get("CHAT_ID", "8039335944")
MODE = os.environ.get("MODE", "daily")

def get_latest_post():
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None
    latest = items[0]
    title = latest.find("title").text.strip()
    link = latest.find("link").text.strip()
    return title, link

def get_post_content(link):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")

    body = post_soup.select_one("div.se-main-container, div#postViewArea")
    if not body:
        return ""

    # 전체 텍스트 줄 추출
    raw_lines = body.get_text(separator="\n").split("\n")
    lines = [l.strip() for l in raw_lines if l.strip()]

    # 은(실버) 관련 섹션만 추출
    silver_lines = []
    capture = False
    for line in lines:
        # 은/실버 관련 키워드가 나오면 캡처 시작
        if re.search(r'은바|실버|은판|silver|Silver|은\s*\(', line, re.IGNORECASE):
            capture = True
        # 금/골드 관련 키워드가 나오면 캡처 중단 (은 섹션 끝)
        if capture and re.search(r'순금|골드|금바|금판|팔라듐|백금|platinum', line, re.IGNORECASE):
            break
        if capture:
            silver_lines.append(line)

    # 은 섹션을 못 찾으면 전체에서 가격 줄만 표시
    if not silver_lines:
        silver_lines = [l for l in lines if re.search(r'은|실버|silver', l, re.IGNORECASE)]

    # 가격 라인 정리: "3,900,000\n원 (이체)" → "3,900,000원 (이체)" 합치기
    cleaned = []
    i = 0
    while i < len(silver_lines):
        line = silver_lines[i]
        # 숫자,숫자 패턴이고 다음 줄이 '원'으로 시작하면 합치기
        if re.match(r'^[\d,]+$', line) and i + 1 < len(silver_lines) and silver_lines[i+1].startswith('원'):
            cleaned.append(line + silver_lines[i+1])
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

def load_last_hash():
    try:
        with open("last_post.txt", "r") as f:
            return f.read().strip()
    except:
        return ""

def save_last_hash(price_hash):
    with open("last_post.txt", "w") as f:
        f.write(price_hash)

if __name__ == "__main__":
    title, link = get_latest_post()
    if not link:
        print("게시글을 찾을 수 없습니다.")
    elif MODE == "daily":
        content = get_post_content(link)
        msg = build_message(title, link, content, prefix="📊 [매일 11시] 은 최신 시세")
        send_telegram(msg)
        print(msg)
    elif MODE == "check":
        content = get_post_content(link)
        current_hash = get_price_hash(content)
        last_hash = load_last_hash()
        if current_hash != last_hash:
            msg = build_message(title, link, content, prefix="🆕 은 시세 변경 알림!")
            send_telegram(msg)
            save_last_hash(current_hash)
            print(f"시세 변경 감지: {title}")
        else:
            print("시세 변경 없음")
