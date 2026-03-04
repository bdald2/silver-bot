import requests
from bs4 import BeautifulSoup
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8023059821:AAGGn4tcg60mOmRDMC7sI386P2BAzC-LqYk")
CHAT_ID = os.environ.get("CHAT_ID", "8039335944")
MODE = os.environ.get("MODE", "daily")  # daily 또는 check

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

def build_message(title, link, prefix="📊 순수한금 최신 시세"):
    content = get_post_content(link)
    if content:
        return f"{prefix}\n\n{title}\n\n{content}\n\n🔗 {link}"
    return f"{prefix}\n\n{title}\n\n🔗 {link}"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)

def load_last_link():
    try:
        with open("last_post.txt", "r") as f:
            return f.read().strip()
    except:
        return ""

def save_last_link(link):
    with open("last_post.txt", "w") as f:
        f.write(link)

if __name__ == "__main__":
    title, link = get_latest_post()
    if not link:
        print("게시글을 찾을 수 없습니다.")
    elif MODE == "daily":
        msg = build_message(title, link, prefix="📊 [매일 11시] 순수한금 최신 시세")
        send_telegram(msg)
        print(msg)
    elif MODE == "check":
        last_link = load_last_link()
        if link != last_link:
            msg = build_message(title, link, prefix="🆕 새 글 알림!")
            send_telegram(msg)
            save_last_link(link)
            print(f"새 글 발견: {title}")
        else:
            print("새 글 없음")
