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

SILVER_KEYWORDS = r'ìë§¤ì|ì\s*íë§¤|ì¤ë²|silver|ì\s*ë§¤ì|ìê·¸ëë¼|ìë°'
GOLD_KEYWORDS = r'ê¸ë§¤ì|ê¸\s*íë§¤|ê³¨ë|ìê¸|ììíê¸|gold|ê¸\s*ë§¤ì|ê³¨ëë°|ê¸ë°'

SILVER_CAPTURE = r'ìë°|ì¤ë²|ìí|silver|ì\s*ë§¤ì|ìê·¸ëë¼'
SILVER_STOP = r'ìê¸|ê³¨ëë°|ê¸ë°|íë¼ë|ë°±ê¸'
GOLD_CAPTURE = r'ìê¸|ììíê¸|ê³¨ëë°|ê¸ë°|ê¸\s*ë§¤ì|ê¸í|ê³¨ë'
GOLD_STOP = r'ìë°|ì¤ë²|ìí|íë¼ë|ë°±ê¸'


def get_latest_post(keyword_pattern):
    """RSSìì í¤ìë ê´ë ¨ ìµì  ê¸ ì°¾ê¸°. ìì¼ë©´ ìµì  ê¸ ë°í."""
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
        print(f"[ì¤ë¥] RSS íì± ì¤í¨: {e}")
        return None, None


def get_post_content(link, capture_pattern, stop_pattern):
    """ë¸ë¡ê·¸ í¬ì¤í¸ìì ê´ë ¨ ê°ê²© ë´ì© ì¶ì¶."""
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
            print("[ê²½ê³ ] í¬ì¤í¸ ë³¸ë¬¸ì ì°¾ì ì ììµëë¤.")
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
            result_lines = [l for l in lines if re.search(r'[\d,]+\s*ì', l)]
        cleaned = []
        i = 0
        while i < len(result_lines):
            line = result_lines[i]
            if (re.match(r'^[\d,]+$', line) and i + 1 < len(result_lines)
                and re.match(r'^ì', result_lines[i + 1])):
                cleaned.append(line + result_lines[i + 1])
                i += 2
            else:
                cleaned.append(line)
                i += 1
        return "\n".join(cleaned[:15]) if cleaned else ""
    except Exception as e:
        print(f"[ì¤ë¥] í¬ì¤í¸ ë´ì© ì¶ì¶ ì¤í¨: {e}")
        return ""


def extract_prices(content):
    prices = re.findall(r'[\d,]+\s*ì', content)
    prices = [''.join(p.split()) for p in prices]
    return "|".join(prices)


def get_content_hash(link, content):
    """í¬ì¤í¸ ë§í¬ + ê°ê²© ì ë³´ë¡ í´ì ìì± â ì ê²ìê¸ OR ê°ê²©ë³ë ëª¨ë ê°ì§"""
    prices = extract_prices(content)
    if not prices:
        return ""
    combined = link + "|" + prices
    return hashlib.md5(combined.encode()).hexdigest()


def mark_changed_lines(old_link, old_content, new_link, new_content):
    """ë³ê²½ë ê°ê²© ë¼ì¸ì (ë³ë) íì ì¶ê°.
    - ë§í¬ê° ë¤ë¥´ë©´ ì í¬ì¤í¸ì´ë¯ë¡ (ë³ë) íì ìì´ ë°í
    - ë§í¬ê° ê°ê³  ê°ê²©ì´ ë¬ë¼ì§ë©´ í´ë¹ ë¼ì¸ì (ë³ë) íì
    """
    if old_link != new_link or not old_content:
        # ì í¬ì¤í¸ì´ê±°ë ì´ì  ë°ì´í° ìì â (ë³ë) íì ìì´ ë°í
        return new_content

    old_lines = set(old_content.split("\n"))
    new_lines = new_content.split("\n")
    marked = []
    for line in new_lines:
        if re.search(r'[\d,]+\s*ì', line) and line not in old_lines:
            marked.append(line + " (ë³ë)")
        else:
            marked.append(line)
    return "\n".join(marked)


def save_last_state(link, content, filename):
    """ë§í¬ì ê°ê²© ë´ì©ì íì¼ì ì ì¥"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(link + "\n---\n" + content)
    print(f"[ìºì] {filename} ì ì¥ ìë£")


def load_last_state(filename):
    """ì ì¥ë ë§í¬ì ê°ê²© ë´ì© ë¡ë. (link, content) ë°í"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = f.read()
        if "\n---\n" in data:
            link, content = data.split("\n---\n", 1)
            print(f"[ìºì] {filename} ë¡ë ìë£")
            return link.strip(), content.strip()
        else:
            # êµ¬ íì(í´ìë§ ì ì¥ë ê²½ì°) â ë¹ ê° ë°í
            return "", ""
    except FileNotFoundError:
        print(f"[ìºì] {filename} ìì â ì²« ì¤íì¼ë¡ ê°ì£¼")
        return "", ""


def build_message(title, link, content, prefix="ð ìì¸"):
    if content:
        return f"{prefix}\n\n{title}\n\n{content}\n\nð {link}"
    return f"{prefix}\n\n{title}\n\nð {link}"


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[ì¤ë¥] TELEGRAM_TOKEN ëë CHAT_ID íê²½ë³ìê° ì¤ì ëì§ ìììµëë¤.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        print("[ì±ê³µ] íë ê·¸ë¨ ë©ìì§ ì ì¡ ìë£")
    except Exception as e:
        print(f"[ì¤ë¥] íë ê·¸ë¨ ì ì¡ ì¤í¨: {e}")


def load_last_hash(filename):
    try:
        with open(filename, "r") as f:
            val = f.read().strip()
            print(f"[ìºì] {filename} ë¡ë: {val[:8] if val else '(ë¹ì´ìì)'}")
            return val
    except FileNotFoundError:
        print(f"[ìºì] {filename} ìì â ì²« ì¤íì¼ë¡ ê°ì£¼")
        return ""


def save_last_hash(content_hash, filename):
    with open(filename, "w") as f:
        f.write(content_hash)
        print(f"[ìºì] {filename} ì ì¥: {content_hash[:8]}...")


if __name__ == "__main__":
    print(f"=== ì¤í ëª¨ë: {MODE} ===")

    # ââ ê¸°ì¡´ ë¨ë ëª¨ë (íì í¸í ì ì§) ââââââââââââââââââââââââââââââââââââââ

    if MODE == "daily":
        title, link = get_latest_post(SILVER_KEYWORDS)
        if not link:
            print("ì ê²ìê¸ì ì°¾ì ì ììµëë¤.")
        else:
            content = get_post_content(link, SILVER_CAPTURE, SILVER_STOP)
            msg = build_message(title, link, content, prefix="ð [ë§¤ì¼ 11ì] ì ìµì  ìì¸")
            send_telegram(msg)
            print(msg)

    elif MODE == "gold_daily":
        title, link = get_latest_post(GOLD_KEYWORDS)
        if not link:
            print("ê¸ ê²ìê¸ì ì°¾ì ì ììµëë¤.")
        else:
            content = get_post_content(link, GOLD_CAPTURE, GOLD_STOP)
            msg = build_message(title, link, content, prefix="ð [ë§¤ì¼ 11ì] ê¸ ìµì  ìì¸")
            send_telegram(msg)
            print(msg)

    elif MODE == "check":
        title, link = get_latest_post(SILVER_KEYWORDS)
        if not link:
            print("ì ê²ìê¸ì ì°¾ì ì ììµëë¤.")
        else:
            content = get_post_content(link, SILVER_CAPTURE, SILVER_STOP)
            current_hash = get_content_hash(link, content)
            last_hash = load_last_hash("last_silver_post.txt")
            print(f"íì¬ í´ì: {current_hash[:8] if current_hash else '(ì¶ì¶ ì¤í¨)'}")
            print(f"ì´ì  í´ì: {last_hash[:8] if last_hash else '(ìì)'}")
            if not current_hash:
                print("[ê²½ê³ ] ê°ê²© ì ë³´ë¥¼ ì¶ì¶íì§ ëª»íìµëë¤. í´ì ì ì¥ ìëµ.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="ð ì ìê¸/ìì¸ ë³ê²½ ìë¦¼!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_silver_post.txt")
                print(f"ì ë³ê²½ ê°ì§: {title}")
            else:
                print("ì ë³ê²½ ìì")

    elif MODE == "gold_check":
        title, link = get_latest_post(GOLD_KEYWORDS)
        if not link:
            print("ê¸ ê²ìê¸ì ì°¾ì ì ììµëë¤.")
        else:
            content = get_post_content(link, GOLD_CAPTURE, GOLD_STOP)
            current_hash = get_content_hash(link, content)
            last_hash = load_last_hash("last_gold_post.txt")
            print(f"íì¬ í´ì: {current_hash[:8] if current_hash else '(ì¶ì¶ ì¤í¨)'}")
            print(f"ì´ì  í´ì: {last_hash[:8] if last_hash else '(ìì)'}")
            if not current_hash:
                print("[ê²½ê³ ] ê°ê²© ì ë³´ë¥¼ ì¶ì¶íì§ ëª»íìµëë¤. í´ì ì ì¥ ìëµ.")
            elif current_hash != last_hash:
                msg = build_message(title, link, content, prefix="ð ê¸ ìê¸/ìì¸ ë³ê²½ ìë¦¼!")
                send_telegram(msg)
                save_last_hash(current_hash, "last_gold_post.txt")
                print(f"ê¸ ë³ê²½ ê°ì§: {title}")
            else:
                print("ê¸ ë³ê²½ ìì")

    # ââ íµí© ëª¨ë (ìë¡ ì¶ê°) ââââââââââââââââââââââââââââââââââââââââââââââââ

    elif MODE == "combined_daily":
        # ì + ê¸ ì¼ì¼ ìì¸ë¥¼ íëì ë©ìì§ë¡ ì ì¡
        silver_title, silver_link = get_latest_post(SILVER_KEYWORDS)
        gold_title, gold_link = get_latest_post(GOLD_KEYWORDS)

        parts = ["ð [ë§¤ì¼ 11ì] ì/ê¸ ìµì  ìì¸"]

        if silver_link:
            silver_content = get_post_content(silver_link, SILVER_CAPTURE, SILVER_STOP)
            parts.append(f"ð¥ [ì ìì¸]\n{silver_content}\nð {silver_link}")
        else:
            parts.append("ð¥ [ì ìì¸]\n(ë°ì´í° ìì)")

        if gold_link:
            gold_content = get_post_content(gold_link, GOLD_CAPTURE, GOLD_STOP)
            parts.append(f"ð¥ [ê¸ ìì¸]\n{gold_content}\nð {gold_link}")
        else:
            parts.append("ð¥ [ê¸ ìì¸]\n(ë°ì´í° ìì)")

        msg = "\n\n".join(parts)
        send_telegram(msg)
        print(msg)

    elif MODE == "combined_check":
        # ì + ê¸ ìì¸ë¥¼ í¨ê» ì²´í¬íì¬ ë³ë ì íëì ë©ìì§ë¡ ì ì¡
        # ê°ê²©ì´ ë°ë ë¼ì¸ìë§ (ë³ë) íì
        silver_title, silver_link = get_latest_post(SILVER_KEYWORDS)
        gold_title, gold_link = get_latest_post(GOLD_KEYWORDS)

        silver_changed = False
        gold_changed = False
        silver_marked_content = ""
        gold_marked_content = ""

        # ââ ì ì²´í¬ ââ
        if silver_link:
            silver_content = get_post_content(silver_link, SILVER_CAPTURE, SILVER_STOP)
            silver_hash = get_content_hash(silver_link, silver_content)
            old_silver_link, old_silver_content = load_last_state("last_silver_state.txt")
            old_silver_hash = get_content_hash(old_silver_link, old_silver_content) if old_silver_content else ""

            print(f"[ì] íì¬ í´ì: {silver_hash[:8] if silver_hash else '(ì¶ì¶ ì¤í¨)'}")
            print(f"[ì] ì´ì  í´ì: {old_silver_hash[:8] if old_silver_hash else '(ìì)'}")

            if not silver_hash:
                print("[ì] ê°ê²© ì ë³´ ì¶ì¶ ì¤í¨ â ì ì¥ ìëµ")
            elif silver_hash != old_silver_hash:
                silver_marked_content = mark_changed_lines(
                    old_silver_link, old_silver_content, silver_link, silver_content
                )
                save_last_state(silver_link, silver_content, "last_silver_state.txt")
                silver_changed = True
                print(f"[ì] ë³ê²½ ê°ì§: {silver_title}")
            else:
                print("[ì] ë³ê²½ ìì")
        else:
            print("[ì] ê²ìê¸ì ì°¾ì ì ììµëë¤.")

        # ââ ê¸ ì²´í¬ ââ
        if gold_link:
            gold_content = get_post_content(gold_link, GOLD_CAPTURE, GOLD_STOP)
            gold_hash = get_content_hash(gold_link, gold_content)
            old_gold_link, old_gold_content = load_last_state("last_gold_state.txt")
            old_gold_hash = get_content_hash(old_gold_link, old_gold_content) if old_gold_content else ""

            print(f"[ê¸] íì¬ í´ì: {gold_hash[:8] if gold_hash else '(ì¶ì¶ ì¤í¨)'}")
            print(f"[ê¸] ì´ì  í´ì: {old_gold_hash[:8] if old_gold_hash else '(ìì)'}")

            if not gold_hash:
                print("[ê¸] ê°ê²© ì ë³´ ì¶ì¶ ì¤í¨ â ì ì¥ ìëµ")
            elif gold_hash != old_gold_hash:
                gold_marked_content = mark_changed_lines(
                    old_gold_link, old_gold_content, gold_link, gold_content
                )
                save_last_state(gold_link, gold_content, "last_gold_state.txt")
                gold_changed = True
                print(f"[ê¸] ë³ê²½ ê°ì§: {gold_title}")
            else:
                print("[ê¸] ë³ê²½ ìì")
        else:
            print("[ê¸] ê²ìê¸ì ì°¾ì ì ììµëë¤.")

        # ââ ë³ë ìì¼ë©´ íµí© ë©ìì§ 1ê° ë°ì¡ ââ
        if silver_changed or gold_changed:
            parts = ["ð ì/ê¸ ìì¸ ë³ë ìë¦¼!"]

            if silver_changed:
                parts.append(f"ð¥ [ì ìì¸]\n{silver_marked_content}\nð {silver_link}")

            if gold_changed:
                parts.append(f"ð¥ [ê¸ ìì¸]\n{gold_marked_content}\nð {gold_link}")

            msg = "\n\n".join(parts)
            send_telegram(msg)
            print(msg)
        else:
            print("ì/ê¸ ëª¨ë ë³ê²½ ìì â ìë¦¼ ìì")

    else:
        print(f"[ì¤ë¥] ì ì ìë MODE: {MODE}")
