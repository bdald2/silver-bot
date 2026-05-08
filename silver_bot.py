# -*- coding: utf-8 -*-
"""
silver-bot: 순수한금 블로그(wolfkickbox)에서 금/은 시세를 모니터링.

- 데이터 소스: 네이버 블로그 RSS + 모바일 페이지 HTML 스크래핑
- 추출 조건: Brand 일반 / Payment 현금 / Unit 원/g 또는 원/kg
- 운영 정책: 변경 감지(combined_check) 전용 — 스케줄성 일일 알림 없음
- 알림 트리거: 은 또는 금 가격 중 하나라도 직전 캐시 대비 바뀌면 1회 통합 발송
- 시간대: 모든 로그/시각은 KST(UTC+9) 기준
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo

# ───────── 상수 ─────────
KST = ZoneInfo("Asia/Seoul")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
MODE = os.environ.get("MODE", "combined_check")

LAST_SILVER_FILE = "last_silver_state.txt"
LAST_GOLD_FILE = "last_gold_state.txt"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ───────── 유틸 ─────────
def now_kst_str() -> str:
    """현재 KST 시각을 디버그 로그용 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


# ───────── RSS / 본문 ─────────
def get_latest_post():
    """RSS에서 은/실버 키워드 글 우선 검색. (같은 글에 금/은 둘 다 포함됨)"""
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {"User-Agent": USER_AGENT}
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None

    # 제목에 은/실버 포함된 글 우선
    for item in items:
        title = item.find("title").text.strip()
        if re.search(r'은바|실버|은전|silver', title, re.IGNORECASE):
            link = item.find("link").text.strip()
            return title, link

    # 없으면 최신 글 반환
    latest = items[0]
    return latest.find("title").text.strip(), latest.find("link").text.strip()


def _fetch_lines(link: str) -> list:
    """포스트 본문에서 trim된 텍스트 라인 리스트 추출."""
    headers = {"User-Agent": USER_AGENT}
    log_no = link.split("wolfkickbox/")[-1].split("?")[0]
    mobile_url = f"https://m.blog.naver.com/wolfkickbox/{log_no}"
    post_res = requests.get(mobile_url, headers=headers, timeout=10)
    post_soup = BeautifulSoup(post_res.text, "html.parser")

    body = (
        post_soup.select_one("div.se-main-container")
        or post_soup.select_one("div#postViewArea")
        or post_soup.select_one("div.post-view")
        or post_soup.select_one("div#content")
    )
    if not body:
        return []

    raw_lines = body.get_text(separator="\n").split("\n")
    return [l.strip() for l in raw_lines if l.strip()]


def _extract_section(lines: list, start_pattern: str, end_pattern: str) -> list:
    """start_pattern을 만나면 capture 시작, end_pattern을 만나면 중단."""
    section = []
    capture = False
    for line in lines:
        if not capture and re.search(start_pattern, line, re.IGNORECASE):
            capture = True
        elif capture and re.search(end_pattern, line, re.IGNORECASE):
            break
        if capture:
            section.append(line)
    return section


def _clean_lines(section_lines: list) -> list:
    """숫자만 있는 줄 + 다음 '원' 시작 줄을 합쳐서 정리 (기존 로직 그대로)."""
    cleaned = []
    i = 0
    while i < len(section_lines):
        line = section_lines[i]
        if (
            re.match(r'^[\d,]+$', line)
            and i + 1 < len(section_lines)
            and re.match(r'^원', section_lines[i + 1])
        ):
            cleaned.append(line + section_lines[i + 1])
            i += 2
        else:
            cleaned.append(line)
            i += 1
    return cleaned


def get_post_sections(link: str):
    """포스트에서 silver/gold 두 섹션 추출 (한 번의 HTML fetch).
    반환: (silver_text, gold_text)"""
    lines = _fetch_lines(link)
    if not lines:
        return "", ""

    # 은(silver) 섹션 — 기존 정규식 그대로 보존
    silver_lines = _extract_section(
        lines,
        start_pattern=r'은바|실버|은판|silver|은\s*\(|은\s*매입',
        end_pattern=r'순금|골드바|금바|팔라듐|백금',
    )
    # 못 찾으면 가격 포함 줄로 폴백 (기존 동작 유지)
    if not silver_lines:
        silver_lines = [l for l in lines if re.search(r'[\d,]+\s*원', l)]

    # 금(gold) 섹션 — silver의 종료 키워드(`순금|골드바|금바`)를 시작 키워드로 활용
    gold_lines = _extract_section(
        lines,
        start_pattern=r'순금|골드바|금바|gold|금\s*\(|금\s*매입',
        end_pattern=r'은바|실버|은판|silver|팔라듐|백금|구리|로듐',
    )

    silver_text = "\n".join(_clean_lines(silver_lines)[:15])
    gold_text = "\n".join(_clean_lines(gold_lines)[:15])
    return silver_text, gold_text


# ───────── 가격 비교 ─────────
def extract_price_numbers(content: str) -> list:
    """가격 숫자만 정수 리스트로 추출 (전일 대비 비교용)."""
    raw = re.findall(r'([\d,]+)\s*원', content)
    out = []
    for p in raw:
        n = p.replace(",", "")
        if n.isdigit() and len(n) >= 4:  # 너무 작은 숫자(부가설명)는 제외
            out.append(int(n))
    return out


def determine_direction(current_prices: list, last_prices: list) -> str:
    """전일 대비 방향: ↑(인상) / ↓(인하) / =(혼조 또는 동일) / 신규(비교 불가)."""
    if not last_prices or not current_prices:
        return "🆕 신규"

    n = min(len(current_prices), len(last_prices))
    if n == 0:
        return "🆕 신규"

    ups = sum(1 for i in range(n) if current_prices[i] > last_prices[i])
    downs = sum(1 for i in range(n) if current_prices[i] < last_prices[i])
    diff = current_prices[0] - last_prices[0]

    if ups > downs:
        return f"↑ 인상 ({diff:+,}원)"
    if downs > ups:
        return f"↓ 인하 ({diff:+,}원)"
    if ups == 0 and downs == 0:
        return "= 변동없음"
    return f"= 혼조 ({diff:+,}원)"


# ───────── 캐시 ─────────
def load_last_prices(filepath: str) -> list:
    """저장된 전일 가격 리스트 로드 (콤마 구분 정수)."""
    try:
        with open(filepath, "r") as f:
            txt = f.read().strip()
        if not txt:
            return []
        # 구버전 호환: 해시값 등 비숫자 문자열은 무시
        if not all(p.strip().isdigit() for p in txt.split(",") if p.strip()):
            return []
        return [int(x) for x in txt.split(",") if x.strip().isdigit()]
    except Exception:
        return []


def save_current_prices(filepath: str, prices: list) -> None:
    with open(filepath, "w") as f:
        f.write(",".join(str(p) for p in prices))


# ───────── 메시지 ─────────
def build_combined_message(
    title: str,
    link: str,
    silver_content: str,
    silver_prices: list,
    gold_content: str,
    gold_prices: list,
    head_line: str,
) -> str:
    """이전 버전(🔔 헤더 + 🥇 금 / 🥈 은 섹션 + 구분선 + 링크) 형식으로 메시지 빌드.

    - 가격이 정상 추출된 섹션만 출력 (빈/오인 추출 섹션은 스킵)
    - 금이 먼저, 은이 나중 (이전 버전 순서 그대로)
    - 시간대는 KST 명시
    """
    parts = []
    parts.append(f"🔔 금/은 시세 변동 알림!\n{head_line}\n({now_kst_str()})")

    if title:
        parts.append(title)

    if gold_content and gold_prices:
        parts.append(f"🥇 [금 시세]\n{gold_content}")
    if silver_content and silver_prices:
        parts.append(f"🥈 [은 시세]\n{silver_content}")

    parts.append("------------------------------------------")
    parts.append(f"🔗 {link}")
    return "\n\n".join(parts)


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data, timeout=10)


# ───────── 메인 ─────────
def main() -> None:
    print(f"[{now_kst_str()}] silver-bot 실행 시작 (MODE={MODE})")

    title, link = get_latest_post()
    if not link:
        print("  ✖ 게시글을 찾을 수 없습니다.")
        return

    print(f"  · 최신 글: {title}")
    print(f"  · 링크: {link}")

    silver_content, gold_content = get_post_sections(link)
    silver_prices = extract_price_numbers(silver_content)
    gold_prices = extract_price_numbers(gold_content)
    last_silver = load_last_prices(LAST_SILVER_FILE)
    last_gold = load_last_prices(LAST_GOLD_FILE)

    print(f"  · 은 현재가: {silver_prices}")
    print(f"  · 금 현재가: {gold_prices}")
    print(f"  · 은 직전가: {last_silver}")
    print(f"  · 금 직전가: {last_gold}")

    if MODE not in ("check", "combined_check"):
        print(f"  ✖ 알 수 없는 MODE: {MODE} — 종료")
        return

    silver_changed = bool(silver_prices) and silver_prices != last_silver
    gold_changed = bool(gold_prices) and gold_prices != last_gold

    if not (silver_changed or gold_changed):
        print("  · 시세 변경 없음 — 캐시 유지")
        return

    silver_dir = determine_direction(silver_prices, last_silver) if silver_prices else ""
    gold_dir = determine_direction(gold_prices, last_gold) if gold_prices else ""

    if silver_changed and gold_changed:
        head_line = f"은 {silver_dir} / 금 {gold_dir}"
    elif silver_changed:
        head_line = f"은 {silver_dir}"
    else:
        head_line = f"금 {gold_dir}"

    msg = build_combined_message(
        title=title,
        link=link,
        silver_content=silver_content,
        silver_prices=silver_prices,
        gold_content=gold_content,
        gold_prices=gold_prices,
        head_line=head_line,
    )
    send_telegram(msg)

    if silver_prices:
        save_current_prices(LAST_SILVER_FILE, silver_prices)
    if gold_prices:
        save_current_prices(LAST_GOLD_FILE, gold_prices)

    print(f"  ✓ 시세 변경 감지 — 텔레그램 발송 완료")


if __name__ == "__main__":
    main()
