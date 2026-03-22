import requests
from bs4 import BeautifulSoup
import os
import re
import hashlib

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
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

    # 제목에 은/실버 포함된 글 우선 탐색 (최근 20개 중)
    for item in items[:20]:
        title = item.find("title").text.strip()
        if re.search(r'은매입|은판|실버|silver', title, re.IGNORECASE):
            link = item.find("link").text.strip()
            return title, link

    # 없으면 최신 글 반환
    latest = items[0]
    return latest.find("title").text.strip(), latest.find("link").text.strip()


def get_post_content(link):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")

    # 여러 셀렉터 시도
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

    # 은(실버) 관련 섹션만 추출
    silver_lines = []
    capture = False
    for line in lines:
        if re.search(r'은바|실버|은판|silver|은\s*매입', line, re.IGNORECASE):
            capture = True
        # 금/골드 섹션 시작 시 중단
        if capture and re.search(r'순금|골드바|금바|팔라듐|백금', line, re.IGNORECASE):
            break
        if capture:
            silver_lines.append(line)

    # 은 섹션 못 찾으면 가격 포함된 줄만
    if not silver_lines:
        silver_lines = [l for l in lines if re.search(r'[\d,]+\s*원', l)]

    # 줄 정리: 숫자만 있는 줄 + 다음 줄 "원..." → 합치기
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
    res = requests.post(url, data=data, timeout=10)
    if not res.ok:
        print(f"텔레그램 전송 실패: {res.status_code} {res.text}")


def load_last_hash():
    try:
        with open("last_post.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
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
        save_last_hash(get_price_hash(content))
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
