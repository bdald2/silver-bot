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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")
    body = post_soup.select_one("div.se-main-container, section.se-section, div#postViewArea")
    if body:
        lines = body.get_text(separator="\n").strip().split("\n")
        lines = [l.strip() for l in lines if l.strip()]
        return "\n".join(lines[:20])
    return ""

def extract_prices(content):
    # 가격 숫자만 추출 (예: 4,400,000원)
    prices = re.findall(r'[\d,]+원', content)
    return "|".join(prices)

def get_price_hash(content):
    prices = extract_prices(content)
    return hashlib.md5(prices.encode()).hexdigest()

def build_message(title, link, content, prefix="📊 순수한금 최신 시세"):
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
        msg = build_message(title, link, content, prefix="📊 [매일 11시] 순수한금 최신 시세")
        send_telegram(msg)
        print(msg)
    elif MODE == "check":
        content = get_post_content(link)
        current_hash = get_price_hash(content)
        last_hash = load_last_hash()
        if current_hash != last_hash:
            msg = build_message(title, link, content, prefix="🆕 시세 변경 알림!")
            send_telegram(msg)
            save_last_hash(current_hash)
            print(f"시세 변경 감지: {title}")
        else:
            print("시세 변경 없음")
