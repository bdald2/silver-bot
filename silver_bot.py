import os
import hashlib
import json
import requests
import feedparser
from datetime import datetime, timezone, timedelta

# ── 설정 ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("8023059821:AAGGn4tcg60mOmRDMC7sI386P2BAzC-LqYk")
CHAT_ID        = os.environ.get("8039335944")
BLOG_RSS_URL   = "https://blog.naver.com/PostRSSList.naver?blogId=sungsungkeum&widgetTypeCall=true"
STATE_FILE     = "silver_state.json"

KST = timezone(timedelta(hours=9))

# 새벽 0시~7시(KST) 사이에는 알림 발송 안 함
QUIET_START = 0   # 0시
QUIET_END   = 7   # 7시

# ── 유틸 함수 ──────────────────────────────────────────
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def compute_hash(title: str, summary: str) -> str:
    """제목+내용 기반 해시 → 타임스탬프 변경 무시"""
    raw = (title + summary).encode("utf-8")
    return hashlib.md5(raw).hexdigest()

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_quiet_time() -> bool:
    """현재 KST 시각이 새벽 조용한 시간대인지 확인"""
    now_hour = datetime.now(KST).hour
    return QUIET_START <= now_hour < QUIET_END

# ── 메인 로직 ──────────────────────────────────────────
def check_blog():
    now_kst = datetime.now(KST)
    print(f"[{now_kst.strftime('%Y-%m-%d %H:%M KST')}] 순수한금 블로그 확인 중...")

    feed = feedparser.parse(BLOG_RSS_URL)
    if not feed.entries:
        print("RSS 항목 없음, 종료")
        return

    state = load_state()
    changed_posts = []

    for entry in feed.entries[:5]:  # 최신 5개만 확인
        post_id  = entry.get("id") or entry.get("link", "")
        title    = entry.get("title", "")
        summary  = entry.get("summary", "") or entry.get("description", "")
        link     = entry.get("link", "")

        new_hash = compute_hash(title, summary)
        old_hash = state.get(post_id, {}).get("hash")

        if new_hash != old_hash:
            if old_hash is None:
                action = "🆕 새 글"
            else:
                action = "✏️ 수정된 글"
            changed_posts.append((action, title, link))

        # 상태 업데이트 (타임스탬프 아닌 해시 기준)
        state[post_id] = {"hash": new_hash, "title": title}

    save_state(state)

    if not changed_posts:
        print("변경사항 없음")
        return

    # ── 새벽 시간대 필터 ──
    if is_quiet_time():
        print(f"새벽 조용한 시간대({QUIET_START}~{QUIET_END}시 KST) — 알림 생략")
        return

    # ── 텔레그램 발송 ──
    for action, title, link in changed_posts:
        msg = (
            f"{action} 감지 — 순수한금 블로그\n\n"
            f"📌 <b>{title}</b>\n"
            f"🔗 {link}\n\n"
            f"⏰ {now_kst.strftime('%Y-%m-%d %H:%M')} KST"
        )
        send_telegram(msg)
        print(f"알림 발송: {action} — {title}")

if __name__ == "__main__":
    check_blog()
