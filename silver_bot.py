import requests
from bs4 import BeautifulSoup
import os
import re

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
MODE = os.environ.get("MODE", "daily")

LAST_FILE = "last_post.txt"


def get_latest_post():
    """RSS에서 은/실버 관련 최신 글 찾기. 없으면 최신 글 반환."""
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None

    # 제목에 은/실버 포함된 글 우선 탐색
    for item in items:
        title = item.find("title").text.strip()
        if re.search(r'은매입|은판|실버|silver', title, re.IGNORECASE):
            link = item.find("link").text.strip()
            return title, link

    # 없으면 최신 글 반환
    latest = items[0]
    return latest.find("title").text.strip(), latest.find("link").text.strip()


def get_post_content(link):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
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

    # 은(실버) 관련 섹션만 추출
    silver_lines = []
    capture = False
    for line in lines:
        if re.search(r'은바|실버|은판|silver|은\s*\(|은\s*매입', line, re.IGNORECASE):
            capture = True
        # 금/팔라듐 등 다른 금속 섹션 시작 시 중단
        if capture and re.search(r'순금|골드바|금바|팔라듐|백금', line, re.IGNORECASE):
            break
        if capture:
            silver_lines.append(line)

    # 은 섹션 못 찾으면 가격 포함된 줄만 표시
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


def extract_price_numbers(content):
    """가격 숫자만 정수 리스트로 추출 (전일 대비 비교용)"""
    raw = re.findall(r'([\d,]+)\s*원', content)
    out = []
    for p in raw:
        n = p.replace(",", "")
        if n.isdigit() and len(n) >= 4:  # 너무 작은 숫자(부가설명용)는 제외
            out.append(int(n))
    return out


def determine_direction(current_prices, last_prices):
    """전일 가격 대비 방향 판정: ↑(인상) / ↓(인하) / = (혼조 또는 동일) / 🆕(비교 불가)"""
    if not last_prices or not current_prices:
        return "🆕 신규"

    n = min(len(current_prices), len(last_prices))
    if n == 0:
        return "🆕 신규"

    ups = sum(1 for i in range(n) if current_prices[i] > last_prices[i])
    downs = sum(1 for i in range(n) if current_prices[i] < last_prices[i])

    # 첫 가격 변동폭(원) 계산해서 함께 표시
    diff = current_prices[0] - last_prices[0]

    if ups > downs:
        return f"📈 변동↑ (인상 {diff:+,}원)"
    elif downs > ups:
        return f"📉 변동↓ (인하 {diff:+,}원)"
    else:
        # ups == downs이고 둘 다 0이면 동일, 아니면 혼조
        if ups == 0 and downs == 0:
            return "↔ 변동없음"
        else:
            return f"🔀 혼조 ({diff:+,}원)"


def build_message(title, link, content, prefix):
    if content:
        return f"{prefix}\n\n{title}\n\n{content}\n\n🔗 {link}"
    return f"{prefix}\n\n{title}\n\n🔗 {link}"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data)


def load_last_prices():
    """저장된 전일 가격 리스트 로드 (콤마로 구분된 정수)"""
    try:
        with open(LAST_FILE, "r") as f:
            txt = f.read().strip()
        if not txt:
            return []
        # 구버전 호환: 해시값(영문/숫자 혼합 32자)이 들어있으면 무시
        if not all(p.strip().isdigit() for p in txt.split(",") if p.strip()):
            return []
        return [int(x) for x in txt.split(",") if x.strip().isdigit()]
    except Exception:
        return []


def save_current_prices(prices):
    with open(LAST_FILE, "w") as f:
        f.write(",".join(str(p) for p in prices))


if __name__ == "__main__":
    title, link = get_latest_post()
    if not link:
        print("게시글을 찾을 수 없습니다.")
    else:
        content = get_post_content(link)
        current_prices = extract_price_numbers(content)
        last_prices = load_last_prices()

        if MODE == "daily":
            direction = determine_direction(current_prices, last_prices)
            prefix = f"📊 [매일 11시] 은 최신 시세\n{direction}"
            msg = build_message(title, link, content, prefix=prefix)
            send_telegram(msg)
            save_current_prices(current_prices)
            print(msg)

        elif MODE == "check":
            if current_prices != last_prices:
                direction = determine_direction(current_prices, last_prices)
                prefix = f"🆕 은 시세 변경 알림!\n{direction}"
                msg = build_message(title, link, content, prefix=prefix)
                send_telegram(msg)
                save_current_prices(current_prices)
                print(f"시세 변경 감지: {title}")
            else:
                print("시세 변경 없음")
