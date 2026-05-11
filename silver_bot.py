# -*- coding: utf-8 -*-
"""
silver-bot: 순수한금 블로그(wolfkickbox)에서 금/은 시세를 모니터링.

- 데이터 소스: 네이버 블로그 RSS + 모바일 페이지 HTML 스크래핑
- 추출 조건: Brand 일반 / Payment 현금 / Unit 원/g 또는 원/kg
- 운영 정책: 변경 감지(combined_check) 전용 — 스케줄성 일일 알림 없음
- 알림 트리거: 은 또는 금 가격 중 하나라도 직전 캐시 대비 바뀌면 1회 통합 발송
- 글 검색 정책: RSS에서 금 키워드/은 키워드 글을 각각 최신으로 검색
  · 같은 글이면 한 번만 fetch해서 두 섹션 추출
  · 다른 글이면 각 글에서 해당 섹션만 추출
  · RSS에 해당 글이 없거나 파싱 실패하면 직전 캐시(JSON)로 폴백 표시
- 표시 정책:
  · 알림 발송 시 항상 금·은 두 섹션을 모두 표시 (캐시라도 가져와서 표시)
  · 변동 방향 표시(↑/↓/=)는 실제 변경된 쪽만 head에 붙음
  · 변경된 가격 줄 끝에 '(변동)' 마킹 추가 (캐시 폴백/신규는 마킹 없음)
- 시간대: 모든 로그/시각은 KST(UTC+9) 기준
- 캐시 형식: JSON {"prices":[...], "content":"...", "title":"...", "link":"..."}
  · 구버전(콤마 구분 정수만)도 읽기 가능 (마이그레이션 자동)
"""

import os
import re
import json
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

# RSS 글 제목에서 금/은 글을 식별할 키워드
SILVER_TITLE_PATTERN = r'은매입|은판매|실버|은바|은전'
GOLD_TITLE_PATTERN = r'금매입|금판매|골드바|순금'

# 금 섹션에서 통째로 제거할 안내성 키워드 (검인제품/차감 노트 등)
GOLD_DROP_KEYWORDS = ('부터', '차감', '검인')


# ───────── 유틸 ─────────
def now_kst_str() -> str:
    """현재 KST 시각을 디버그 로그용 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


# ───────── RSS / 본문 ─────────
def get_latest_silver_and_gold_posts():
    """RSS에서 은 글·금 글 각각의 최신 게시글을 반환.

    같은 글이 두 키워드 모두 매치하면 (예: '금/은매입시세') 같은 (title, link)가
    silver_post와 gold_post에 모두 들어옴.

    반환: (silver_post, gold_post)  — 각각 (title, link) 튜플 또는 None
    """
    rss_url = "https://rss.blog.naver.com/wolfkickbox.xml"
    headers = {"User-Agent": USER_AGENT}
    res = requests.get(rss_url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "xml")
    items = soup.find_all("item")
    if not items:
        return None, None

    silver_post = None
    gold_post = None
    for item in items:
        title = item.find("title").text.strip()
        link = item.find("link").text.strip()
        if silver_post is None and re.search(SILVER_TITLE_PATTERN, title, re.IGNORECASE):
            silver_post = (title, link)
        if gold_post is None and re.search(GOLD_TITLE_PATTERN, title, re.IGNORECASE):
            gold_post = (title, link)
        if silver_post and gold_post:
            break

    return silver_post, gold_post


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


# ───────── 표시용 줄 압축 (가격 추출 후에만 적용) ─────────
def compact_gold_lines(gold_text: str) -> str:
    """금 섹션 표시용으로 라벨/단위/가격 줄을 한 줄로 압축.

    예시:
      '순금\\n골드바,덩어리\\n3.75g당\\n823,000원 (현찰)'
        → '순금골드바,덩어리 3.75g당 823,000원 (현찰)'

    규칙:
      - '원' 포함 가격 줄 만나면 직전 라벨 줄들과 결합
      - buf 마지막이 숫자만(예: '9')이면 가격 줄과 직접 붙임
      - 안내성 노트(검인제품/원부터/차감)는 그룹 통째로 제거 (실가격 아님)
      - 라벨이 4개 초과면 앞쪽은 헤더로 보고 단독 라인으로 분리
      - 라벨이 정확히 3개: 첫 두 라벨 공백 없이 결합 + 셋째는 공백 (브랜드+상세 패턴)

    주의: '표시용' 변환이므로 가격 추출(extract_price_numbers)은
    반드시 이 함수 호출 이전의 원본 텍스트에 대해 수행해야 함.
    """
    if not gold_text:
        return gold_text

    lines = gold_text.split('\n')
    result = []
    buf = []
    for line in lines:
        is_price = ('원' in line) and bool(re.search(r'\d', line))
        if is_price:
            if buf and re.match(r'^[\d,]+$', buf[-1]):
                price_line = buf[-1] + line
                buf = buf[:-1]
            else:
                price_line = line

            full_text = ' '.join(buf) + ' ' + price_line
            if any(k in full_text for k in GOLD_DROP_KEYWORDS):
                buf = []
                continue

            while len(buf) > 3:
                result.append(buf.pop(0))

            if len(buf) == 0:
                result.append(price_line)
            elif len(buf) == 1:
                result.append(f"{buf[0]} {price_line}")
            elif len(buf) == 3:
                result.append(f"{buf[0]}{buf[1]} {buf[2]} {price_line}")
            else:
                result.append(f"{' '.join(buf)} {price_line}")
            buf = []
        else:
            buf.append(line)

    result.extend(buf)
    return '\n'.join(result)


def mark_changed_lines(content: str, current_prices: list, last_prices: list) -> str:
    """가격이 변경된 줄 끝에 방향 이모지 마킹 추가.

    - 줄별로 등장하는 4자리 이상 가격을 순서대로 매칭하여
      직전 캐시(last_prices)와 같은 인덱스 위치의 값과 비교
    - 인상된 가격: 🔥↑ / 인하된 가격: ❄️↓
    - 줄 내 첫 번째로 변경된 가격의 방향을 해당 줄 전체 마커로 사용
    - last_prices가 비어 있으면 '신규' 상태로 보고 마킹하지 않음
    - current_prices와 content는 동일 순서로 가격이 등장해야 함 (이 봇 형식 보장)
    """
    if not last_prices or not current_prices:
        return content

    lines = content.split('\n')
    out = []
    idx = 0
    for line in lines:
        line_prices = []
        for raw in re.findall(r'([\d,]+)\s*원', line):
            n = raw.replace(",", "")
            if n.isdigit() and len(n) >= 4:
                line_prices.append(int(n))
        if line_prices:
            marker = ""
            for p in line_prices:
                if not marker:  # 줄 내 첫 변경 가격의 방향만 사용
                    if idx >= len(last_prices):
                        marker = " 🔥↑"
                    elif p > last_prices[idx]:
                        marker = " 🔥↑"
                    elif p < last_prices[idx]:
                        marker = " ❄️↓"
                idx += 1
            if marker:
                line = f"{line}{marker}"
        out.append(line)
    return '\n'.join(out)


# ───────── 캐시 (JSON, 구버전 호환) ─────────
def load_last_state(filepath: str) -> dict:
    """직전 상태 로드. 반환 dict: {prices, content, title, link}.

    파일이 신버전(JSON)이면 그대로 파싱.
    구버전(콤마 구분 정수)이면 prices만 채워서 반환 (마이그레이션 자동).
    """
    default = {"prices": [], "content": "", "title": "", "link": ""}
    try:
        with open(filepath, "r") as f:
            txt = f.read().strip()
        if not txt:
            return default
        # 신버전(JSON) 시도
        try:
            data = json.loads(txt)
            if isinstance(data, dict):
                return {
                    "prices": data.get("prices", []) or [],
                    "content": data.get("content", "") or "",
                    "title": data.get("title", "") or "",
                    "link": data.get("link", "") or "",
                }
        except json.JSONDecodeError:
            pass
        # 구버전: 콤마 구분 정수
        parts = [p.strip() for p in txt.split(",") if p.strip()]
        if parts and all(p.isdigit() for p in parts):
            return {
                "prices": [int(p) for p in parts],
                "content": "",
                "title": "",
                "link": "",
            }
        return default
    except Exception:
        return default


def save_current_state(filepath: str, prices: list, content: str, title: str, link: str) -> None:
    """직전 상태 저장 (JSON). 한글은 그대로 저장 (ensure_ascii=False)."""
    data = {
        "prices": prices,
        "content": content,
        "title": title,
        "link": link,
    }
    with open(filepath, "w") as f:
        json.dump(data, f, ensure_ascii=False)


# ───────── 메시지 ─────────
def build_combined_message(
    silver_post,    # (title, link) | None
    gold_post,      # (title, link) | None
    silver_content: str,
    silver_prices: list,
    gold_content: str,
    gold_prices: list,
    head_line: str,
) -> str:
    """🔔 헤더 + 🥇 금 / 🥈 은 섹션 + 구분선 + 링크 형식으로 메시지 빌드.

    - 가격이 추출된 섹션은 변동 여부와 무관하게 항상 표시 (캐시라도 표시)
    - 금이 먼저, 은이 나중 (이전 버전 순서)
    - 같은 글이면 링크 1회만, 다른 글이면 섹션별로 링크 표시
    - head_line은 실제 변경된 쪽만 표시 (변경 없는 쪽은 (변동) 표시 생략)
    - 시간대는 KST 명시
    """
    same_link = (
        silver_post is not None
        and gold_post is not None
        and silver_post[1] == gold_post[1]
    )

    parts = []
    parts.append(f"🔔 금/은 시세 변동 알림!\n{head_line}\n({now_kst_str()})")

    if gold_content and gold_prices and gold_post:
        gold_title, gold_link = gold_post
        section = f"🥇 [금 시세]\n{gold_title}\n\n{gold_content}"
        if not same_link:
            section += f"\n\n🔗 {gold_link}"
        parts.append(section)

    if silver_content and silver_prices and silver_post:
        silver_title, silver_link = silver_post
        section = f"🥈 [은 시세]\n{silver_title}\n\n{silver_content}"
        if not same_link:
            section += f"\n\n🔗 {silver_link}"
        parts.append(section)

    parts.append("------------------------------------------")
    if same_link and silver_post:
        parts.append(f"🔗 {silver_post[1]}")

    return "\n\n".join(parts)


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, data=data, timeout=10)


# ───────── 메인 ─────────
def main() -> None:
    print(f"[{now_kst_str()}] silver-bot 실행 시작 (MODE={MODE})")

    # 1) RSS에서 현재 시점의 금/은 글 검색
    silver_post, gold_post = get_latest_silver_and_gold_posts()
    print(f"  · 은 글(RSS): {silver_post[0] if silver_post else '없음'}")
    print(f"  · 금 글(RSS): {gold_post[0] if gold_post else '없음'}")

    # 2) 본문 fetch
    silver_content = ""
    gold_content = ""
    if silver_post and gold_post and silver_post[1] == gold_post[1]:
        silver_content, gold_content = get_post_sections(silver_post[1])
    else:
        if silver_post:
            silver_content, _ = get_post_sections(silver_post[1])
        if gold_post:
            _, gold_content = get_post_sections(gold_post[1])

    # 3) 가격 추출 (압축 이전 원본 텍스트로)
    silver_prices = extract_price_numbers(silver_content)
    gold_prices = extract_price_numbers(gold_content)

    # 4) 캐시 로드
    silver_state = load_last_state(LAST_SILVER_FILE)
    gold_state = load_last_state(LAST_GOLD_FILE)
    last_silver = silver_state["prices"]
    last_gold = gold_state["prices"]

    # 5) RSS 결과가 비었거나 가격 추출 실패 시 캐시로 폴백 (표시는 직전 데이터로)
    if (not silver_post or not silver_prices) and silver_state.get("link"):
        print("  · 은 RSS 없음/파싱 실패 → 캐시 사용")
        silver_post = (silver_state["title"], silver_state["link"])
        silver_content = silver_state["content"]
        silver_prices = silver_state["prices"]

    if (not gold_post or not gold_prices) and gold_state.get("link"):
        print("  · 금 RSS 없음/파싱 실패 → 캐시 사용")
        gold_post = (gold_state["title"], gold_state["link"])
        gold_content = gold_state["content"]
        gold_prices = gold_state["prices"]

    # 6) 캐시 저장용 원본 보존 (압축/마킹 이전)
    silver_content_orig = silver_content
    gold_content_orig = gold_content

    # 7) 표시용 압축 (금 섹션만 — 가격 추출 이후 적용)
    gold_content = compact_gold_lines(gold_content)

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

    # 8) 변경된 가격 줄에 '(변동)' 마킹 (변경된 쪽만, 신규/캐시폴백은 마킹 없음)
    if silver_changed:
        silver_content = mark_changed_lines(silver_content, silver_prices, last_silver)
    if gold_changed:
        gold_content = mark_changed_lines(gold_content, gold_prices, last_gold)

    silver_dir = determine_direction(silver_prices, last_silver) if silver_prices else ""
    gold_dir = determine_direction(gold_prices, last_gold) if gold_prices else ""

    # head_line은 변경된 쪽만 표시
    if silver_changed and gold_changed:
        head_line = f"은 {silver_dir} / 금 {gold_dir}"
    elif silver_changed:
        head_line = f"은 {silver_dir}"
    else:
        head_line = f"금 {gold_dir}"

    msg = build_combined_message(
        silver_post=silver_post,
        gold_post=gold_post,
        silver_content=silver_content,
        silver_prices=silver_prices,
        gold_content=gold_content,
        gold_prices=gold_prices,
        head_line=head_line,
    )
    send_telegram(msg)

    # 9) 캐시 갱신 (변경된 쪽만 — 가격 + 본문 + 제목 + 링크 함께 저장)
    if silver_changed and silver_post:
        save_current_state(
            LAST_SILVER_FILE,
            silver_prices,
            silver_content_orig,
            silver_post[0],
            silver_post[1],
        )
    if gold_changed and gold_post:
        save_current_state(
            LAST_GOLD_FILE,
            gold_prices,
            gold_content_orig,
            gold_post[0],
            gold_post[1],
        )

    print(f"  ✓ 시세 변경 감지 — 텔레그램 발송 완료")


if __name__ == "__main__":
    main()
        )
    if gold_changed and gold_post:
        save_current_state(
            LAST_GOLD_FILE,
            gold_prices,
            gold_content_orig,
            gold_post[0],
            gold_post[1],
        )

    print(f"  ✓ 시세 변경 감지 — 텔레그램 발송 완료")


if __name__ == "__main__":
    main()
