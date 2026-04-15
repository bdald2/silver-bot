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

SILVER_KEYWORDS = r'은매입|은\s*판매|실버|silver|은\s*매입|은그래뉴라|은바'
GOLD_KEYWORDS = r'금매입|금\s*판매|골드|실금|순수한금|gold|금\s*매입|골드바|금바'

SILVER_CAPTURE = r'은바|실버|은판|silver|은\s*매입|은그래뉴라'
SILVER_STOP = r'실금|골드바|금바|플라라|백금'
GOLD_CAPTURE = r'실금|순수한금|골드바|금바|금\s*매입|금판|골드'
GOLD_STOP = r'은바|실버|은판|플라라|백금'


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
        post_res.encoding = 'utf-8'
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


def get_content_hash(link, content):
    """포스트 링크 + 가격 정보로 해시 생성"""
    prices = extract_prices(content)
    if not prices:
        return ""
    combined = link + "|" + prices
    return hashlib.md5(combined.encode()).hexdigest()


def _parse_price_line(line):
    m = re.search(r'([\d,]+)\s*원', line)
    if not m:
        return line.strip(), None
    try:
        num = int(m.group(1).replace(',', ''))
    except ValueError:
        return line.strip(), None
    prefix = line[:m.start()].strip()
    suffix = line[m.end():].strip()
    return f"{prefix}||{suffix}", num


def mark_changed_lines(old_link, old_content, new_link, new_content):
    if old_link != new_link or not old_content:
        return new_content
    old_map = {}
    for l in old_content.split("\n"):
        label, num = _parse_price_line(l)
        if num is not None and label:
            old_map[label] = num
    marked = []
    for line in new_content.split("\n"):
        label, num = _parse_price_line(line)
        if num is None or not label:
            marked.append(line)
            continue
        old_num = old_map.get(label)
        if old_num is None or old_num == num:
            marked.append(line)
        elif num > old_num:
            marked.append(f"{line} 🔺 (변동)")
        else:
            marked.append(f"{line} 🔻 (변동)")
    return "\n".join(marked)


def save_last_state(link, content, filename):
    """링크와 가격 내용을 파일에 저장"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(link + "\n---\n" + content)
    print(f"[캐시] {filename} 저장 완료")


def load_last_state(filename):
    """저장된 링크와 가격 내용 로드. (link, content) 반환"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = f.read()
        if "\n---\n" in data:
            link, content = data.split("\n---\n", 1)
            print(f"[캐시] {filename} 로드 완료")
            return link.strip(), content.strip()
        else:
            return "", ""
    except FileNotFoundError:
        print(f"[캐시] {filename} 없음 - 첫 실행으로 간주")
        return "", ""


def build_message(title, link, content, prefix="📊 새소식"):
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
        print(f"[캐시] {filename} 없음 - 첫 실행으로 간주")
        return ""


def save_last_hash(content_hash, filename):
    with open(filename, "w") as f:
        f.write(content_hash)
    print(f"[캐시] {filename} 저장: {content_hash[:8]}...")


if __name__ == "__main__":
    print(f"=== 실행 모드: {MODE} ===")

    # --- 기존 단독 모드 (하위 호환 유지) ---
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
            current_hash = get_content_hash(link, content)
            last_hash = load_last_hash("last_silver_post.txt")
            print(f"현재 해시: {current_hash[:8] if current_hash else '(추출 실패)'}")
            print(f"이전 해시: {last_hash[:8] if last_hash else '(없음)'}")
            if not current_hash:
                print("[경고] 가격 정보를 추출하지 못했습니다.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🔔 은 시세/시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_silver_post.txt")
                print(f"은 변경 감지: {title}")
            else:
                print("은 변경 없음")

    elif MODE == "gold_check":
        title, link = get_latest_post(GOLD_KEYWORDS)
        if not link:
            print("금 게시글을 찾을 수 없습니다.")
        else:
            content = get_post_content(link, GOLD_CAPTURE, GOLD_STOP)
            current_hash = get_content_hash(link, content)
            last_hash = load_last_hash("last_gold_post.txt")
            print(f"현재 해시: {current_hash[:8] if current_hash else '(추출 실패)'}")
            print(f"이전 해시: {last_hash[:8] if last_hash else '(없음)'}")
            if not current_hash:
                print("[경고] 가격 정보를 추출하지 못했습니다.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="🔔 금 시세/시세 변경 알림!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_gold_post.txt")
                print(f"금 변경 감지: {title}")
            else:
                print("금 변경 없음")

    # --- 통합 모드 (새로 추가) ---
    elif MODE == "combined_daily":
        silver_title, silver_link = get_latest_post(SILVER_KEYWORDS)
        gold_title, gold_link = get_latest_post(GOLD_KEYWORDS)
        parts = ["📊 [매일 11시] 금/은 최신 시세"]
        if gold_link:
            gold_content = get_post_content(gold_link, GOLD_CAPTURE, GOLD_STOP)
            parts.append(f"🥇 [금 시세]\n{gold_content}")
        else:
            parts.append("🥇 [금 시세]\n(데이터 없음)")
        if silver_link:
            silver_content = get_post_content(silver_link, SILVER_CAPTURE, SILVER_STOP)
            parts.append(f"🥈 [은 시세]\n{silver_content}\n🔗 {silver_link}")
        else:
            parts.append("🥈 [은 시세]\n(데이터 없음)")
        msg = "\n\n".join(parts)
        send_telegram(msg)
        print(msg)

    elif MODE == "combined_check":
        silver_title, silver_link = get_latest_post(SILVER_KEYWORDS)
        gold_title, gold_link = get_latest_post(GOLD_KEYWORDS)
        silver_changed = False
        gold_changed = False
        silver_marked_content = ""
        gold_marked_content = ""

        # --- 은 체크 ---
        if silver_link:
            silver_content = get_post_content(silver_link, SILVER_CAPTURE, SILVER_STOP)
            silver_hash = get_content_hash(silver_link, silver_content)
            old_silver_link, old_silver_content = load_last_state("last_silver_state.txt")
            old_silver_hash = get_content_hash(old_silver_link, old_silver_content) if old_silver_content else ""
            print(f"[은] 현재 해시: {silver_hash[:8] if silver_hash else '(추출 실패)'}")
            print(f"[은] 이전 해시: {old_silver_hash[:8] if old_silver_hash else '(없음)'}")
            if not silver_hash:
                print("[은] 가격 정보 추출 실패 - 저장 생략")
            elif silver_hash != old_silver_hash:
                silver_marked_content = mark_changed_lines(
                    old_silver_link, old_silver_content, silver_link, silver_content
                )
                save_last_state(silver_link, silver_content, "last_silver_state.txt")
                silver_changed = True
                print(f"[은] 변경 감지: {silver_title}")
            else:
                print("[은] 변경 없음")
        else:
            print("[은] 게시글을 찾을 수 없습니다.")

        # --- 금 체크 ---
        if gold_link:
            gold_content = get_post_content(gold_link, GOLD_CAPTURE, GOLD_STOP)
            gold_hash = get_content_hash(gold_link, gold_content)
            old_gold_link, old_gold_content = load_last_state("last_gold_state.txt")
            old_gold_hash = get_content_hash(old_gold_link, old_gold_content) if old_gold_content else ""
            print(f"[금] 현재 해시: {gold_hash[:8] if gold_hash else '(추출 실패)'}")
            print(f"[금] 이전 해시: {old_gold_hash[:8] if old_gold_hash else '(없음)'}")
            if not gold_hash:
                print("[금] 가격 정보 추출 실패 - 저장 생략")
            elif gold_hash != old_gold_hash:
                gold_marked_content = mark_changed_lines(
                    old_gold_link, old_gold_content, gold_link, gold_content
                )
                save_last_state(gold_link, gold_content, "last_gold_state.txt")
                gold_changed = True
                print(f"[금] 변경 감지: {gold_title}")
            else:
                print("[금] 변경 없음")
        else:
            print("[금] 게시글을 찾을 수 없습니다.")

        # --- 변동 있으면 통합 메시지 1개 발송 ---
        if silver_changed or gold_changed:
            parts = ["🔔 금/은 시세 변동 알림!"]
            if gold_changed:
                parts.append(f"🥇 [금 시세]\n{gold_marked_content}")
            if silver_changed:
                parts.append(f"🥈 [은 시세]\n{silver_marked_content}\n🔗 {silver_link}")
            msg = "\n\n".join(parts)
            send_telegram(msg)
            print(msg)
        else:
            print("은/금 모두 변경 없음 - 알림 없음")

    else:
        print(f"[오류] 알 수 없는 MODE: {MODE}")
