import requests
from bs4 import BeautifulSoup
import os
import re
import hashlib

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
MODE = os.environ.get("MODE", "daily")

BLOG_ID = "wolfkickbox"
RSS_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SILVER_KEYWORDS = r'은매입|은\s*판매|실버|silver|은\s*매입|은그래뉼|은바'
GOLD_KEYWORDS   = r'금매입|금\s*판매|골드|순금|gold|금\s*매입|골드바|금바'

SILVER_CAPTURE  = r'은바|실버|은판|silver|은\s*매입|은그래뉼'
SILVER_STOP     = r'순금|골드바|금바|팔라듐|백금'

GOLD_CAPTURE    = r'순금|골드바|금바|금\s*매입|금판|골드'
GOLD_STOP       = r'은바|실버|은판|팔라듐|백금'


def get_latest_post(keyword_pattern):
    """RSS에서 키워드 관련 최신 글 찾기. 없으면 최신 글 반환."""
    try:
        res = requests.get(RSS_URL, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "xml")
        items = soup.find_all("item")
        if not items:
            return None, None

        for item in items[:20]:
            title = item.find("title").text.strip()
            if re.search(keyword_pattern, title, re.IGNORECASE):
                link = item.find("link").text.strip()
                return title, link

        latest = items[0]
        return latest.find("title").text.strip(), latest.find("link").text.strip()
    except Exception as e:
        print(f"[오류] RSS 파싱 실패: {e}")
        return None, None


def get_post_content(link, capture_pattern, stop_pattern):
    """블로그 포스트에서 관련 가격 내용 추출."""
    try:
        log_no = link.split(f"{BLOG_ID}/")[-1].split("?")[0]
        mobile_url = f"https://m.blog.naver.com/{BLOG_ID}/{log_no}"
        post_res = requests.get(mobile_url, headers=HEADERS, timeout=10)
        post_soup = BeautifulSoup(post_res.text, "html.parser")

        body = (
            post_soup.select_one("div.se-main-container")
            or post_soup.select_one("div#postViewArea")
            or post_soup.select_one("div.post-view")
            or post_soup.select_one("div#content")
        )
        if not body:
            print("[경고] 포스트 본문을 찾을 수 없습니다.")
            return ""

        raw_lines = body.get_text(separator="\n").split("\n")
        lines = [l.strip() for l in raw_lines if l.strip()]

        result_lines = []
        capturing = False
        for line in lines:
            if re.search(capture_pattern, line, re.IGNORECASE):
                capturing = True
            if capturing and re.search(stop_pattern, line, re.IGNORECASE):
                break
            if capturing:
                result_lines.append(line)

        if not result_lines:
            result_lines = [l for l in lines if re.search(r'[\d,]+\s*원', l)]

        cleaned = []
        i = 0
        while i < len(result_lines):
            line = result_lines[i]
            if (re.match(r'^[\d,]+$', line)
                    and i + 1 < len(result_lines)
                    and re.match(r'^원', result_lines[i + 1])):
                cleaned.append(line + result_lines[i + 1])
                i += 2
            else:
                cleaned.append(line)
                i += 1

        return "\n".join(cleaned[:15]) if cleaned else ""
    except Exception as e:
        print(f"[오류] 포스트 내용 추출 실패: {e}")
        return ""


def extract_prices(content):
    prices = re.findall(r'[\d,]+\s*원', content)
    prices = [''.join(p.split()) for p in prices]
    return "|".join(prices)


def get_price_hash(content):
    prices = extract_prices(content)
    if not prices:
        return ""
    return hashlib.md5(prices.encode()).hexdigest()


def build_message(title, link, content, prefix="📊 시세"):
    if content:
        return f"{prefix}\n\n{title}\n\n{content}\n\n🔗 {link}"
    return f"{prefix}\n\n{title}\n\n🔗 {link}"


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[오류] TELEGRAM_TOKEN 또는 CHAT_ID 환경변수가 설정되지 않았습니다.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        print("[성공] 텔레그램 메시지 전송 완료")
    except Exception as e:
        print(f"[오류] 텔레그램 전송 실패: {e}")


def load_last_hash(filename):
    try:
        with open(filename, "r") as f:
            val = f.read().strip()
            print(f"[캐시] {filename} 로드: {val[:8] if val else '(비어있음)'}")
            return val
    except FileNotFoundError:
        print(f"[캐시] {filename} 없음 → 첫 실행으로 간주")
        return ""


def save_last_hash(price_hash, filename):
    with open(filename, "w") as f:
        f.write(price_hash)
    print(f"[캐시] {filename} 저장: {price_hash[:8]}...")


if __name__ == "__main__":
    print(f"=== 실행 모드: {MODE} ===")

    if MODE == "daily":
        title, link = get_latest_post(SILVER_KEYWORDS)
        if not link:
            print("은 게시글을 찾을 수 없습니다.")
        else:
            content = get_post_content(link, SILVER_CAPTURE, SILVER_STOP)
            msg = build_message(title, link, content, prefix="📊 [매일 11시] 은 최신 시세")
            send_telegram(msg)
            print(msg)

    elif MODE == "gold_daily":
        title, link = get_latest_post(GOLD_KEYWORDS)
        if not link:
            print("금 게시글을 찾을 수 없습니다.")
        else:
            content = get_post_content(link, GOLD_CAPTURE, GOLD_STOP)
            msg = build_message(title, link, content, prefix="📊 [매일 11시] 금 최신 시세")
            send_telegram(msg)
            print(msg)

    elif MODE == "check":
        title, link = get_latest_post(SILVER_KEYWORDS)
        if not link:
            print("은 게시글을 찾을 수 없습니다.")
        else:
            content = get_post_content(link, SILVER_CAPTURE, SILVER_STOP)
            current_hash = get_price_hash(content)
            last_hash    = load_last_hash("last_silver_post.txt")

            print(f"현재 해시: {current_hash[:8] if current_hash else '(추출 실패)'}")
            print(f"이전 해시: {last_hash[:8] if last_hash else '(없음)'}")

            if not current_hash:
                print("[경고] 가격 정보를 추출하지 못했습니다. 해시 저장 생략.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🆕 은 시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_silver_post.txt")
                print(f"은 시세 변경 감지: {title}")
            else:
                print("은 시세 변경 없음")

    elif MODE == "gold_check":
        title, link = get_latest_post(GOLD_KEYWORDS)
        if not link:
            print("금 게시글을 찾을 수 없습니다.")
        else:
            content = get_post_content(link, GOLD_CAPTURE, GOLD_STOP)
            current_hash = get_price_hash(content)
            last_hash    = load_last_hash("last_gold_post.txt")

            print(f"현재 해시: {current_hash[:8] if current_hash else '(추출 실패)'}")
            print(f"이전 해시: {last_hash[:8] if last_hash else '(없음)'}")

            if not current_hash:
                print("[경고] 가격 정보를 추출하지 못했습니다. 해시 저장 생략.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🆕 금 시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_gold_post.txt")
                print(f"금 시세 변경 감지: {title}")
            else:
                print("금 시세 변경 없음")

    else:
        print(f"[오류] 알 수 없는 MODE: {MODE}")
