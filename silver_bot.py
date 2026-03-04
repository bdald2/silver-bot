import requests
from bs4 import BeautifulSoup
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8023059821:AAGGn4tcg60mOmRDMC7sI386P2BAzC-LqYk")
CHAT_ID = os.environ.get("CHAT_ID", "8039335944")

def get_silver_price():
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(rss_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "xml")
        items = soup.find_all("item")
        if not items:
            return "게시글을 찾을 수 없습니다."

        latest = items[0]
        title = latest.find("title").text.strip()
        link = latest.find("link").text.strip()

        log_no = link.split("wolfkickbox/")[-1].split("?")[0]
        mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
        post_res = requests.get(mobile_url, headers=headers, timeout=10)
        post_soup = BeautifulSoup(post_res.text, "html.parser")

        content = ""
        body = post_soup.select_one("div.se-main-container, section.se-section, div#postViewArea")
        if body:
            lines = body.get_text(separator="\n").strip().split("\n")
            lines = [l.strip() for l in lines if l.strip()]
            content = "\n".join(lines[:20])

        if content:
            return f"📊 순수한금 최신 시세\n\n{title}\n\n{content}\n\n🔗 {link}"
        else:
            return f"📊 순수한금 최신 시세\n\n{title}\n\n🔗 {link}"

    except Exception as e:
        return f"오류 발생: {str(e)}"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)

if __name__ == "__main__":
    msg = get_silver_price()
    send_telegram(msg)
    print(msg)
