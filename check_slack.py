import os
import re
import requests
import time
from datetime import date, datetime, timedelta
from typing import Optional
import pytz
import google.generativeai as genai
from PIL import Image
from io import BytesIO
import json
import base64
from config import FULL_EXEMPT_DATES, SERVICE_END_DATE

# 1. 깃허브 시크릿(환경 변수)에서 토큰과 채널 ID 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# GitHub API — state.json 영속화용
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"
STATE_FILE_PATH = "state.json"
BOMB_MAX = 10_000
BOMB_STEP = 1_000
MONTHLY_EXEMPTION_TOKENS = 1
VALID_EXEMPTION_REASON_KEYWORDS = (
    "질병", "몸살", "감기", "독감", "코로나", "병원", "치과", "진료", "치료",
    "입원", "수술", "컨디션", "건강", "생리통", "두통", "장염",
    "자격증", "시험", "토익", "오픽", "컴활", "sqld", "정처기", "기사", "필기", "실기",
    "면접", "면접준비", "시험준비", "자격증준비",
    "예비군", "출장", "야근", "업무", "프로젝트", "발표", "세미나", "학회",
    "가족", "경조사", "장례", "병문안", "이사",
)
REJECT_EXEMPTION_REASON_KEYWORDS = (
    "귀찮", "놀", "게임", "술", "음주", "회식", "늦잠", "잠들", "하기싫",
)
GEMINI_MODEL_NAME = "gemini-2.5-flash"
GEMINI_LITE_MODEL_NAME = "gemini-2.5-flash-lite"  # 타이브레이킹 전용 (RPD 풀 별도)
GEMINI_BATCH_SIZE = 5               # 배치당 이미지 수 (RPD=20 기준 4배치 = 4 RPD/일)
GEMINI_MIN_INTERVAL_SECONDS = 13    # RPM=5 → 12초/요청, 1초 버퍼
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_BUFFER_SECONDS = 1
GEMINI_FALLBACK_RETRY_SECONDS = 20  # 429 fallback
GEMINI_503_RETRY_SECONDS = 10       # 503 재시도 기본 대기 (attempt * 10s)
model = genai.GenerativeModel(GEMINI_MODEL_NAME)
model_lite = genai.GenerativeModel(GEMINI_LITE_MODEL_NAME)
_last_gemini_call_at = 0.0

# 2. 스터디원 18명 명단 (여기에 아까 메모해둔 ID와 이름을 채워주세요!)
MEMBERS = {
    "U0AGDKJC6AW": "강태규",
    "U0ADY543QDB": "권유현",
    "U0AEWFJQL8G": "김건우",
    "U0AJGEDB9MJ": "김기선",
    "U0AEFT40BEV": "김수현",
    "U0AH924BYKS": "송준수",
    "U0AE6JC1V36": "양승환",
    "U0ADRBPLLNS": "오진호",
    "U0AH7L3FUTX": "이대주",
    "U0AGSGX5QCX": "이민호",
    "U0AE5BQ0VFB": "이아영",
    "U0AE7MCEA2H": "이지민",
    "U0ADXE54A92": "이채연",
    "U0AE5DKQF3K": "장지연",
    "U0AE589NP6G": "최규진",
    "U0AJGDB6W9G": "최보윤",
    "U0ADSS3M1HQ": "홍상우",
    "U0AFNU32D8T": "황지원",
}

# 3. 한국 시간(KST) 기준으로 어제 날짜 포맷팅 (체크봇은 다음날 아침에 실행되므로)
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
yesterday = now - timedelta(days=1)
yesterday_str = yesterday.strftime("%m월 %d일")

# 어제 오전 9시 타임스탬프 (인증 글이 올라오는 시각 기준으로 탐색 범위 제한)
yesterday_9am = yesterday.replace(hour=9, minute=0, second=0, microsecond=0)
oldest_ts = str(yesterday_9am.timestamp())

# Slack API 요청 시 사용할 공통 헤더
headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/x-www-form-urlencoded"
}
# 이미지 다운로드 전용 헤더 (Content-Type 없이 인증만)
img_headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

# Solved.ac 티어 변환 테이블 (난이도 통합 환산 기준 기반)
# level 1-5: 브론즈 5~1 / 6-10: 실버 5~1 / 11-15: 골드 5~1
# 16-20: 플래티넘 5~1 / 21-25: 다이아 5~1 / 26-30: 루비 5~1
_TIER_KR = ["브론즈", "실버", "골드", "플래티넘", "다이아", "루비"]
_SCORE_RANGES = [(1, 22), (23, 55), (56, 85), (86, 100), (97, 100), (100, 100)]

# 프로그래머스 레벨별 환산점수 상하한선 (Gemini 인플레이션 방지용 하드 클램프)
_PROGRAMMERS_CLAMP = {0: (1, 10), 1: (11, 38), 2: (39, 55), 3: (56, 85), 4: (86, 100)}

def build_default_state(target_month: str):
    return {
        "bomb_amount": BOMB_STEP,
        "miss_counts": {name: 0 for name in MEMBERS.values()},
        "exemption_tokens_month": target_month,
        "exemption_tokens": {name: MONTHLY_EXEMPTION_TOKENS for name in MEMBERS.values()},
        "service_end_announced_on": None,
    }

def ensure_state_shape(state, target_month: str):
    changed = False
    state.setdefault("bomb_amount", BOMB_STEP)
    state.setdefault("miss_counts", {})
    for name in MEMBERS.values():
        if name not in state["miss_counts"]:
            state["miss_counts"][name] = 0
            changed = True

    stored_month = state.get("exemption_tokens_month")
    if not isinstance(state.get("exemption_tokens"), dict):
        state["exemption_tokens"] = {}
        changed = True

    if stored_month != target_month:
        state["exemption_tokens_month"] = target_month
        state["exemption_tokens"] = {name: MONTHLY_EXEMPTION_TOKENS for name in MEMBERS.values()}
        changed = True
        print(f"[state] 면제권 월 변경 감지: {stored_month} → {target_month}, 인당 {MONTHLY_EXEMPTION_TOKENS}개로 초기화")
    else:
        for name in MEMBERS.values():
            if name not in state["exemption_tokens"]:
                state["exemption_tokens"][name] = MONTHLY_EXEMPTION_TOKENS
                changed = True

    if "service_end_announced_on" not in state:
        state["service_end_announced_on"] = None
        changed = True

    return state, changed

def load_state(target_month: str):
    """GitHub API로 state.json 읽기. 실패 시 기본값 반환."""
    default = build_default_state(target_month)
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("[state] GITHUB_TOKEN/GITHUB_REPOSITORY 없음. 기본값 사용.")
        return default, None, False
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{STATE_FILE_PATH}"
    gh_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        res = requests.get(url, headers=gh_headers, timeout=10)
        if res.status_code == 404:
            print("[state] state.json 없음. 기본값 사용.")
            return default, None, True
        res.raise_for_status()
        data = res.json()
        content = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
        content, changed = ensure_state_shape(content, target_month)
        return content, data["sha"], changed
    except Exception as e:
        print(f"[state] 읽기 실패: {e}. 기본값 사용.")
        return default, None, True

def save_state(state, sha):
    """GitHub API로 state.json 덮어쓰기."""
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("[state] GITHUB_TOKEN/GITHUB_REPOSITORY 없음. 저장 생략.")
        return
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{STATE_FILE_PATH}"
    gh_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    body = {
        "message": f"chore: update state [{datetime.now(kst).strftime('%Y-%m-%d')}]",
        "content": base64.b64encode(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    try:
        res = requests.put(url, headers=gh_headers, json=body, timeout=10)
        res.raise_for_status()
        print("[state] 저장 완료.")
    except Exception as e:
        print(f"[state] 저장 실패: {e}")

def calc_fines(missing_uids, miss_counts):
    """
    미제출자별 상습 가중처벌액 계산.
    - 폭탄 금액은 미제출자 합산 총액으로 별도 고지 (분담 방식은 자율)
    - 상습 가중: n번째 미제출 시 (n-1)*1000원 개인 추가 납부
    반환: {uid: repeat_penalty} dict, {name: new_miss_count} dict
    """
    penalties = {}
    new_counts = {}
    for uid in missing_uids:
        name = MEMBERS.get(uid, uid)
        prev = miss_counts.get(name, 0)
        new_count = prev + 1
        penalties[uid] = (new_count - 1) * 1000  # 1번째=0, 2번째=1000, n번째=(n-1)*1000
        new_counts[name] = new_count
    return penalties, new_counts

def calc_effective_bomb(bomb_amount):
    """현재 폭탄 표시용 실효 금액. 누적 원금이 0이어도 최소 1,000원."""
    return max(BOMB_STEP, bomb_amount)

def calc_triggered_bomb_total(bomb_amount, missing_count):
    """미제출 발생 시 실제 총 폭탄액. 미제출자 1인당 최소 1,000원 하한을 적용한다."""
    return max(calc_effective_bomb(bomb_amount), missing_count * BOMB_STEP)

def get_solved_ac_info(problem_id: int):
    """Solved.ac API로 백준 문제 실제 난이도 조회. 티어별 점수 범위만 반환하고 세부 점수는 Gemini에게 위임."""
    try:
        res = requests.get(
            "https://solved.ac/api/v3/problem/show",
            params={"problemId": problem_id},
            headers={"Accept": "application/json"},
            timeout=5
        )
        if res.status_code != 200:
            return None
        data = res.json()
        level = data.get("level", 0)
        title = data.get("titleKo") or data.get("title", "")

        if level == 0:
            return {"tier_str": "Unrated", "score_range": None, "title": title, "average_tries": data.get("averageTries")}

        tier_idx = (level - 1) // 5       # 0=브론즈 ... 5=루비
        sub = 5 - ((level - 1) % 5)       # 5=쉬움, 1=어려움 (티어 내)
        tier_str = f"{_TIER_KR[tier_idx]} {sub}"

        return {
            "tier_str": tier_str,
            "score_range": _SCORE_RANGES[tier_idx],
            "title": title,
            "average_tries": data.get("averageTries"),
        }
    except Exception as e:
        print(f"[Solved.ac 조회 실패] problemId={problem_id}, error={e}")
        return None

def extract_boj_number(problem_name: str):
    """문제 이름 문자열에서 백준 문제 번호(4~5자리) 추출
    \b는 Python 3 유니코드 모드에서 한글을 \w로 취급해 '2178번'에서 매칭 실패함.
    숫자 앞뒤에 다른 숫자가 없는 조건으로 대체."""
    match = re.search(r'(?<!\d)(\d{4,5})(?!\d)', problem_name)
    return int(match.group(1)) if match else None

def format_submit_time(ts: float) -> str:
    """unix timestamp → '어제 오후 2시' / '오늘 오전 8시 58분' 형식"""
    dt = datetime.fromtimestamp(ts, tz=kst)
    if dt.date() == yesterday.date():
        day_label = "어제"
    else:
        day_label = "오늘"
    ampm = "오전" if dt.hour < 12 else "오후"
    hour = dt.hour % 12 or 12
    if dt.minute == 0:
        return f"{day_label} {ampm} {hour}시"
    return f"{day_label} {ampm} {hour}시 {dt.minute}분"

def extract_exemption_reason(text: str):
    """'면제권 사용' 댓글에서 사유를 추출한다. 면제권 언급이 없으면 None."""
    normalized = " ".join((text or "").split())
    if "면제권" not in normalized:
        return None

    reason = normalized
    reason = re.sub(r"면제권\s*[가-힣a-zA-Z]*[.。,]?\s*", "", reason)
    reason = re.sub(r"사유\s*[:：-]?\s*", "", reason)
    reason = reason.strip(" :-")
    return reason

def judge_exemption_reason(reason: str):
    """질병/시험/공적 일정 계열이면 승인, 그 외는 보수적으로 반려."""
    trimmed = (reason or "").strip()
    if len(trimmed) < 2:
        return False, "사유가 비어 있거나 너무 짧아요"

    normalized = re.sub(r"\s+", "", trimmed).lower()
    if any(keyword in normalized for keyword in REJECT_EXEMPTION_REASON_KEYWORDS):
        return False, "개인 여가성 사유는 자동 승인 대상이 아니에요"
    if any(keyword in normalized for keyword in VALID_EXEMPTION_REASON_KEYWORDS):
        return True, "합당한 사유로 판단했어요"
    return False, "질병·시험·공적 일정 계열 사유로 보기 어려워 자동 승인하지 않았어요"

def build_exemption_summary(approved_exemptions, rejected_exemptions):
    sections = []

    if approved_exemptions:
        lines = [
            f"  • <@{item['user_id']}>: {item['reason']} (잔여 {item['remaining']}개)"
            for item in approved_exemptions
        ]
        sections.append("\n\n🎟️ *면제권 승인*\n" + "\n".join(lines))

    if rejected_exemptions:
        lines = [
            f"  • <@{item['user_id']}>: {item['reason']} — {item['note']}"
            for item in rejected_exemptions
        ]
        sections.append("\n\n⚠️ *면제권 미승인*\n" + "\n".join(lines))

    return "".join(sections)

def extract_retry_delay_seconds(error) -> Optional[int]:
    """Gemini 429 에러 문자열에서 권장 대기 시간을 뽑아낸다."""
    text = str(error)

    match = re.search(r"Please retry in ([0-9.]+)s", text)
    if match:
        return max(1, int(float(match.group(1)) + 0.999))

    match = re.search(r"retry_delay\s*{[^}]*seconds:\s*(\d+)", text, re.DOTALL)
    if match:
        return max(1, int(match.group(1)))

    return None

def generate_content_with_retry(payload, *, label: str, model_override=None):
    """무료 티어 RPM에 맞춰 간격을 두고, 429/503은 재시도한다.
    model_override: 지정 시 해당 모델 사용 (기본: 전역 model)
    """
    global _last_gemini_call_at
    _model = model_override if model_override is not None else model

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        elapsed = time.time() - _last_gemini_call_at
        if elapsed < GEMINI_MIN_INTERVAL_SECONDS:
            wait_seconds = GEMINI_MIN_INTERVAL_SECONDS - elapsed
            print(f"[Gemini 속도조절] {label}: {wait_seconds:.1f}초 대기")
            time.sleep(wait_seconds)

        try:
            response = _model.generate_content(payload)
            _last_gemini_call_at = time.time()
            return response
        except Exception as e:
            _last_gemini_call_at = time.time()
            error_text = str(e)
            is_rate_limited = (
                "429" in error_text
                or "quota" in error_text.lower()
                or "Resource has been exhausted" in error_text
            )
            is_server_error = (
                "503" in error_text
                or "ServiceUnavailable" in error_text
                or "overloaded" in error_text.lower()
            )
            if not (is_rate_limited or is_server_error) or attempt == GEMINI_MAX_RETRIES:
                raise

            if is_rate_limited:
                retry_seconds = (extract_retry_delay_seconds(e) or GEMINI_FALLBACK_RETRY_SECONDS) + GEMINI_RETRY_BUFFER_SECONDS
                error_label = "429"
            else:
                retry_seconds = GEMINI_503_RETRY_SECONDS * attempt  # 10s, 20s
                error_label = "503"
            print(f"[Gemini 재시도] {label}: {attempt}/{GEMINI_MAX_RETRIES} 실패 ({error_label}), {retry_seconds}초 후 재시도")
            time.sleep(retry_seconds)

def _post_process_result(result):
    """Solved.ac 티어 확인 및 플랫폼별 점수 클램프."""
    if "백준" in result.get("platform", ""):
        problem_num = extract_boj_number(result.get("problem_name", ""))
        if problem_num:
            solved_info = get_solved_ac_info(problem_num)
            if solved_info:
                result["original_tier"] = solved_info["tier_str"]
                result["average_tries"] = solved_info["average_tries"]
                if solved_info["title"]:
                    result["problem_name"] = f"{solved_info['title']} ({problem_num}번)"
                if solved_info["score_range"]:
                    lo, hi = solved_info["score_range"]
                    clamped = max(lo, min(hi, result["converted_score"]))
                    if clamped != result["converted_score"]:
                        print(f"[클램프] 백준 {solved_info['tier_str']} 범위({lo}~{hi}점): {result['converted_score']}점 → {clamped}점")
                    result["converted_score"] = clamped
                print(f"[Solved.ac] {result.get('problem_name')} → {solved_info['tier_str']} ({result['converted_score']}점, 평균 시도 {solved_info['average_tries']}회)")
    elif "프로그래머스" in result.get("platform", ""):
        m = re.search(r"Lv\.(\d)", result.get("original_tier", ""))
        if m:
            lv = int(m.group(1))
            if lv in _PROGRAMMERS_CLAMP:
                lo, hi = _PROGRAMMERS_CLAMP[lv]
                clamped = max(lo, min(hi, result["converted_score"]))
                if clamped != result["converted_score"]:
                    print(f"[클램프] 프로그래머스 Lv.{lv} 점수 {result['converted_score']}점 → {clamped}점으로 조정")
                result["converted_score"] = clamped
    return result

def _build_batch_prompt(n: int, user_list_str: str) -> str:
    return (
        f"너는 '1일 1알고 스터디'의 냉철한 AI 코딩테스트 난이도 판별사야.\n"
        f"아래 {n}명의 알고리즘 제출 이미지가 번호 순서대로 첨부되어 있어:\n"
        f"{user_list_str}\n\n"
        "🚨 [플랫폼 식별 — 반드시 화면을 직접 보고 판단, 문제 이름으로 추측 절대 금지]\n"
        "각 이미지에서 다음 단서를 직접 확인해:\n"
        "• 프로그래머스: URL에 'programmers.co.kr', 초록색 UI, 'Lv.N' 형식 난이도 표기\n"
        "• 백준: URL에 'acmicpc.net', 4~5자리 문제 번호, solved.ac 색깔 원형 배지\n"
        "화면에서 직접 확인이 불가능하면 platform을 \"기타\"로 적어.\n\n"
        "🚨 [점수 다양성 — 같은 레벨이라도 반드시 점수가 달라야 함]\n"
        "같은 Lv.2 / 실버라도 알고리즘 유형·체감 난이도에 따라 다른 점수를 줘.\n"
        "범위 안에서 다양하게 분포시켜. 모든 항목이 같은 점수면 틀린 거야.\n\n"
        "[난이도 통합 환산 기준]\n"
        "백준: 브론즈 1~22점 / 실버 23~55점 / 골드 56~85점 / 플래티넘 86~100점\n"
        "프로그래머스: Lv.0 1~10점 / Lv.1 11~38점 / Lv.2 39~55점 / Lv.3 56~85점 / Lv.4 86~100점\n"
        "다이아몬드·루비·Lv.5는 본 환산 기준 제외.\n\n"
        f"반드시 {n}개 항목을 포함한 JSON 배열로만 답해. 마크다운(```json) 없이 순수 JSON 텍스트만.\n"
        '[{"index": 1, "platform": "백준 또는 프로그래머스", '
        '"problem_name": "문제 이름 (번호 포함)", "original_tier": "골드 1, Lv.3 등 원본 기준 난이도", '
        '"converted_score": 75, "reason": "알고리즘 유형과 체감 난이도를 1문장으로 짧고 유쾌하게"}, ...]'
    )

def analyze_batch(tasks):
    """
    tasks: [(user_id, img_url), ...] GEMINI_BATCH_SIZE개 이하
    반환: [result_dict or None, ...] tasks와 동일 순서
    """
    # 1. 이미지 다운로드 (실패한 건 None으로 표시)
    downloaded = []
    for user_id, img_url in tasks:
        try:
            resp = requests.get(img_url, headers=img_headers, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            downloaded.append((user_id, img))
        except Exception as e:
            print(f"[이미지 다운로드 실패] {MEMBERS.get(user_id, user_id)}: {e}")
            downloaded.append((user_id, None))

    valid = [(uid, img) for uid, img in downloaded if img is not None]
    if not valid:
        return [None] * len(tasks)

    # 2. 프롬프트 + 이미지 페이로드 구성
    n = len(valid)
    user_list_str = "\n".join(f"{i+1}. {MEMBERS.get(uid, uid)}" for i, (uid, _) in enumerate(valid))
    prompt = _build_batch_prompt(n, user_list_str)
    payload = [prompt] + [img for _, img in valid]

    names_label = "+".join(MEMBERS.get(uid, uid) for uid, _ in valid[:2])
    if n > 2:
        names_label += f" 외 {n-2}명"

    # 3. Gemini 호출 + 파싱
    result_map = {}
    try:
        response = generate_content_with_retry(payload, label=f"배치 분석 ({names_label})")
        raw = response.text.strip().replace("```json", "").replace("```", "").strip()
        items = json.loads(raw)
        for item in items:
            idx = int(item.get("index", 0)) - 1
            if 0 <= idx < len(valid):
                uid = valid[idx][0]
                result = {k: v for k, v in item.items() if k != "index"}
                try:
                    result["converted_score"] = int(str(result.get("converted_score", 0)).replace("점", "").strip())
                except ValueError:
                    print(f"[경고] 이상한 점수: {result.get('converted_score')}")
                    result["converted_score"] = 0
                result["user_id"] = uid
                result = _post_process_result(result)
                name = MEMBERS.get(uid, uid)
                print(f"[분석 결과] {name}: {result.get('problem_name')} ({result.get('platform')} · {result.get('original_tier')}) → {result.get('converted_score')}점")
                result_map[uid] = result
    except Exception as e:
        print(f"[배치 분석 실패] {names_label}: {e}")

    return [result_map.get(uid) for uid, _ in tasks]

def compare_with_gemini(a, b):
    """동점자 두 문제를 flash-lite로 직접 비교해 더 어려운 쪽 반환"""
    prompt = (
        f"다음 두 알고리즘 문제 중 어느 것이 더 어렵습니까?\n"
        f"문제 1: {a['problem_name']} ({a['platform']}, {a['original_tier']})\n"
        f"문제 2: {b['problem_name']} ({b['platform']}, {b['original_tier']})\n"
        f"반드시 '1' 또는 '2' 숫자 하나만 출력하세요."
    )
    try:
        res = generate_content_with_retry(
            prompt,
            label=f"동점 비교 {a['problem_name']} vs {b['problem_name']}",
            model_override=model_lite,
        )
        answer = res.text.strip()
        # '2'만 있거나 '2'가 먼저 나오면 b 승, 그 외 a 승
        winner = b if answer.startswith('2') or (('2' in answer) and ('1' not in answer)) else a
        loser = a if winner is b else b
        print(f"[Gemini 비교] '{winner['problem_name']}' > '{loser['problem_name']}'")
        return winner
    except Exception as e:
        print(f"[Gemini 비교 실패] {e}")
        return a

def resolve_tie(tied):
    """동점자 처리:
    - BOJ 끼리 → Solved.ac accepted_user_count 오름차순 (정답자 적을수록 어려움)
    - 그 외    → Gemini 직접 비교 (토너먼트)
    """
    all_boj = all("백준" in r.get("platform", "") for r in tied)
    has_tries = all(r.get("average_tries") is not None for r in tied)

    if all_boj and has_tries:
        winner = max(tied, key=lambda x: x["average_tries"])
        print(f"[동점 처리] BOJ 평균 시도 횟수 기준 → {winner['problem_name']} ({winner['average_tries']}회) 승")
        return winner

    print(f"[동점 처리] Gemini 토너먼트 ({len(tied)}명)")
    winner = tied[0]
    for challenger in tied[1:]:
        winner = compare_with_gemini(winner, challenger)
    return winner

def run_gemini_batch(tasks):
    """GEMINI_BATCH_SIZE 단위 배치로 나눠 순차 처리한다."""
    results = []
    total_batches = (len(tasks) + GEMINI_BATCH_SIZE - 1) // GEMINI_BATCH_SIZE
    for batch_idx in range(total_batches):
        batch = tasks[batch_idx * GEMINI_BATCH_SIZE:(batch_idx + 1) * GEMINI_BATCH_SIZE]
        names = [MEMBERS.get(uid, uid) for uid, _ in batch]
        print(f"배치 {batch_idx+1}/{total_batches} ({len(batch)}명): {', '.join(names)}")
        results.extend(analyze_batch(batch))
    return results

def check_and_notify():
    target_date = yesterday.date()
    target_month = target_date.strftime("%Y-%m")

    # Step 0: 상태 로드 (폭탄 금액 + 미제출 누적 횟수 + 월별 면제권)
    state, state_sha, state_dirty = load_state(target_month)
    bomb_amount = state.get("bomb_amount", 0)
    miss_counts = state.get("miss_counts", {name: 0 for name in MEMBERS.values()})
    exemption_tokens = state.get("exemption_tokens", {name: MONTHLY_EXEMPTION_TOKENS for name in MEMBERS.values()})
    effective_bomb = calc_effective_bomb(bomb_amount)
    print(f"[state] 폭탄 누적={bomb_amount}원 / 실효={effective_bomb}원, 미제출 기록 로드 완료")

    # Step 0-1: 서비스 종료일 이후에는 종료 안내만 한 번 발송
    if target_date >= SERVICE_END_DATE:
        announced_on = None
        if state.get("service_end_announced_on"):
            try:
                announced_on = date.fromisoformat(state["service_end_announced_on"])
            except ValueError:
                print(f"[state] service_end_announced_on 파싱 실패: {state['service_end_announced_on']}")

        if announced_on and announced_on >= SERVICE_END_DATE:
            if state_dirty:
                save_state(state, state_sha)
            print("서비스 종료 안내가 이미 발송되어 추가 검사 없이 종료합니다.")
            return

        closure_text = (
            f"🎓 *[{yesterday_str} 분량] 스터디 운영 종료 안내*\n"
            f"2026년 8월 26일부터는 인증 검사와 벌금 부과를 종료합니다.\n"
            f"지금까지 꾸준히 달려오신 모든 분들 정말 고생 많으셨습니다. "
            f"다들 원하는 곳에 꼭 취업하시길 진심으로 응원할게요! 🍀"
        )
        requests.post("https://slack.com/api/chat.postMessage", headers=headers,
                      data={"channel": CHANNEL_ID, "text": closure_text})
        state["service_end_announced_on"] = target_date.isoformat()
        save_state(state, state_sha)
        print(f"서비스 종료 안내 발송 완료 ({target_date.isoformat()})")
        return

    # Step 0-2: 전원 면제 날짜 확인 — 제출자 없으면 조용히 종료, 있으면 랭킹만 발표
    full_exempt_reason = FULL_EXEMPT_DATES.get(target_date)
    is_exempt = bool(full_exempt_reason)

    # Step A: 오늘 아침에 올라온 '오늘의 인증!' 부모 메시지 찾기
    url_history = "https://slack.com/api/conversations.history"
    params_history = {
        "channel": CHANNEL_ID,
        "limit": 200,
        "oldest": oldest_ts,
    }

    res_history = requests.get(url_history, headers=headers, params=params_history).json()

    target_ts = None
    if res_history.get("ok"):
        for msg in res_history["messages"]:
            if "오늘의 인증!" in msg.get("text", "") and yesterday_str in msg.get("text", ""):
                target_ts = msg["ts"]
                break

    if not target_ts:
        if state_dirty:
            save_state(state, state_sha)
        print("오늘의 인증 글을 찾지 못했습니다.")
        return

    # Step B-0: midnight_report가 이미 조기 종료 선언했는지 확인
    already_closed = False
    if res_history.get("ok"):
        for msg in res_history["messages"]:
            text = msg.get("text", "")
            if "조기 종료" in text and yesterday_str in text:
                already_closed = True
                break

    # Step B: 찾은 부모 메시지에 달린 스레드(댓글) 목록 가져오기
    url_replies = "https://slack.com/api/conversations.replies"
    params_replies = {
        "channel": CHANNEL_ID,
        "ts": target_ts,
    }

    res_replies = requests.get(url_replies, headers=headers, params=params_replies).json()

    submitted_users = set()      # 실제 인증 완료자 (이미지만/이미지+텍스트 모두 인정)
    submission_ts_by_user = {}   # user_id -> 첫 인증 ts
    token_requests = {}          # user_id -> {"reason", "ts"}
    user_images = {}             # user_id -> img_url

    if res_replies.get("ok"):
        for reply in res_replies["messages"]:
            if reply["ts"] == target_ts:
                continue

            user_id = reply.get("user")
            if not user_id or user_id not in MEMBERS:
                continue

            reply_ts = float(reply["ts"])
            files = reply.get("files", [])
            has_image = any(f.get("mimetype", "").startswith("image/") for f in files)

            if has_image:
                submitted_users.add(user_id)
                prev_ts = submission_ts_by_user.get(user_id)
                if prev_ts is None or reply_ts < prev_ts:
                    submission_ts_by_user[user_id] = reply_ts

                if user_id not in user_images:
                    for f in files:
                        if f.get("mimetype", "").startswith("image/"):
                            url = f.get("url_private_download") or f.get("url_private")
                            if url:
                                user_images[user_id] = url
                            break

            reason = extract_exemption_reason(reply.get("text", ""))
            if reason is not None:
                token_requests[user_id] = {"reason": reason, "ts": reply_ts}

    # 면제일 분기: 제출자 없으면 조용히 종료, 있으면 랭킹만 발표하고 return
    if is_exempt:
        if not user_images:
            if state_dirty:
                save_state(state, state_sha)
            print(f"전원 면제일({yesterday_str}, {full_exempt_reason}). 제출자 없음. 조용히 종료.")
            return

        # Gemini 분석
        analysis_tasks = list(user_images.items())
        print(f"[면제일] Gemini 분석 시작: {len(analysis_tasks)}명")
        analysis_results = run_gemini_batch(analysis_tasks)
        valid_results = [r for r in analysis_results if r is not None]
        failed_count = len(analysis_tasks) - len(valid_results)
        if failed_count:
            print(f"[면제일] Gemini 분석 실패 {failed_count}/{len(analysis_tasks)}건")

        master_block = ""
        if not valid_results:
            master_block = "\n\n⚠️ _이미지 분석 전체 실패로 마스터 선정을 건너뜁니다_"
        else:
            top_score = max(r.get("converted_score", 0) for r in valid_results)
            tied = [r for r in valid_results if r.get("converted_score", 0) == top_score]
            best = tied[0] if len(tied) == 1 else resolve_tie(tied)
            winner_id = best["user_id"]
            winner_name = MEMBERS.get(winner_id, "알 수 없음")
            master_block = (
                f"\n🏆 *오늘의 알고리즘 마스터: {winner_name}* (<@{winner_id}>)\n"
                f"📚 `{best['problem_name']}` ({best['platform']} · {best['original_tier']})\n"
                f"💯 난이도 점수: *{best['converted_score']}점*\n"
                f"💬 {best['reason']}"
            )
            runners_up = [r for r in tied if r["user_id"] != winner_id]
            if runners_up:
                mentions = ", ".join(
                    f"<@{r['user_id']}> (`{r['problem_name']}`)"
                    for r in runners_up
                )
                master_block += f"\n\n🥈 *아깝게 탈락한 공동 1등*: {mentions}"
            if failed_count:
                master_block += f"\n\n⚠️ _{failed_count}명 분석 실패 — 해당 참여자는 마스터 선정에서 제외됐습니다_"
            print(f"[면제일] 알고리즘 마스터 선정: {winner_name} ({best['converted_score']}점)")

        ranked_submissions = sorted(submission_ts_by_user.items(), key=lambda item: item[1])
        if len(ranked_submissions) == 1:
            only_id, only_ts = ranked_submissions[0]
            submission_highlight = f"\n🥇 *오늘의 인증자*: <@{only_id}> 님 ({format_submit_time(only_ts)} 제출)"
        elif ranked_submissions:
            first_id, first_ts = ranked_submissions[0]
            last_id, last_ts = ranked_submissions[-1]
            submission_highlight = (
                f"\n🥇 *오늘의 얼리버드*: <@{first_id}> 님 ({format_submit_time(first_ts)} 제출)\n"
                f"🏃 *오늘의 막차 탑승객*: <@{last_id}> 님 ({format_submit_time(last_ts)} 제출 ㄷㄷ)"
            )
        else:
            submission_highlight = ""

        exempt_text = (
            f"📋 *[{yesterday_str} 분량] 자율 제출 랭킹* — {full_exempt_reason}\n"
            f"면제일이지만 자율 참여해 주신 분들이 계셔서 랭킹을 집계했습니다! 👏"
            + submission_highlight
            + master_block
        )
        requests.post("https://slack.com/api/chat.postMessage", headers=headers,
                      data={"channel": CHANNEL_ID, "text": exempt_text})
        if state_dirty:
            save_state(state, state_sha)
        print(f"[면제일] 자율 제출 랭킹 발송 완료. 제출자 {len(user_images)}명.")
        return

    approved_exemption_users = set()
    approved_exemptions = []
    rejected_exemptions = []
    for user_id, request in sorted(token_requests.items(), key=lambda item: item[1]["ts"]):
        if user_id in submitted_users:
            continue

        name = MEMBERS.get(user_id, user_id)
        remaining = exemption_tokens.get(name, MONTHLY_EXEMPTION_TOKENS)
        reason = request["reason"] or "사유 미기재"

        if remaining <= 0:
            rejected_exemptions.append({
                "user_id": user_id,
                "reason": reason,
                "note": "이번 달 면제권을 이미 사용했어요",
            })
            continue

        approved, note = judge_exemption_reason(request["reason"])
        if approved:
            approved_exemption_users.add(user_id)
            exemption_tokens[name] = remaining - 1
            approved_exemptions.append({
                "user_id": user_id,
                "reason": reason,
                "remaining": exemption_tokens[name],
            })
            state_dirty = True
        else:
            rejected_exemptions.append({
                "user_id": user_id,
                "reason": reason,
                "note": note,
            })

    exemption_summary = build_exemption_summary(approved_exemptions, rejected_exemptions)

    # Step C: 스터디원 전체 명단과 비교하여 미제출자 색출
    if already_closed:
        missing_users = []
        print("자정 조기 종료 확인됨. 전원 제출로 처리.")
    else:
        missing_users = [
            f"<@{uid}>" for uid in MEMBERS
            if uid not in submitted_users and uid not in approved_exemption_users
        ]

    # Step D-0: Gemini 알고리즘 마스터 선정 (이미지를 첨부한 제출자 대상)
    master_block = ""
    analysis_tasks = list(user_images.items())
    if analysis_tasks:
        print(f"Gemini 분석 시작: {len(analysis_tasks)}명")
        analysis_results = run_gemini_batch(analysis_tasks)
        valid_results = [r for r in analysis_results if r is not None]
        failed_count = len(analysis_tasks) - len(valid_results)
        if failed_count:
            print(f"Gemini 분석 실패 {failed_count}/{len(analysis_tasks)}건")

        if not valid_results:
            master_block = "\n\n⚠️ _이미지 분석 전체 실패로 마스터 선정을 건너뜁니다_"
            print("Gemini 분석 결과 없음. 마스터 선정 생략.")
        else:
            top_score = max(r.get("converted_score", 0) for r in valid_results)
            tied = [r for r in valid_results if r.get("converted_score", 0) == top_score]
            best = tied[0] if len(tied) == 1 else resolve_tie(tied)
            winner_id = best["user_id"]
            winner_name = MEMBERS.get(winner_id, "알 수 없음")
            master_block = (
                f"\n\n🏆 *오늘의 알고리즘 마스터: {winner_name}* (<@{winner_id}>)\n"
                f"📚 `{best['problem_name']}` ({best['platform']} · {best['original_tier']})\n"
                f"💯 난이도 점수: *{best['converted_score']}점*\n"
                f"💬 {best['reason']}"
            )
            runners_up = [r for r in tied if r["user_id"] != winner_id]
            if runners_up:
                mentions = ", ".join(
                    f"<@{r['user_id']}> (`{r['problem_name']}`)"
                    for r in runners_up
                )
                master_block += f"\n\n🥈 *아깝게 탈락한 공동 1등*: {mentions}"
            if failed_count:
                master_block += f"\n\n⚠️ _{failed_count}명 분석 실패 — 해당 참여자는 마스터 선정에서 제외됐습니다_"
            print(f"알고리즘 마스터 선정: {winner_name} ({best['converted_score']}점)")
    else:
        print("이미지 첨부 없음. 마스터 선정 생략.")

    # Step D: 결과에 따라 슬랙으로 메시지 전송
    if not missing_users:
        submission_highlight = ""
        ranked_submissions = sorted(submission_ts_by_user.items(), key=lambda item: item[1])
        if len(ranked_submissions) == 1:
            only_id, only_ts = ranked_submissions[0]
            submission_highlight = f"\n\n🥇 *오늘의 인증자*: <@{only_id}> 님 ({format_submit_time(only_ts)} 제출)"
        elif ranked_submissions:
            first_id, first_ts = ranked_submissions[0]
            last_id, last_ts = ranked_submissions[-1]
            submission_highlight = (
                f"\n\n🥇 *오늘의 얼리버드*: <@{first_id}> 님 ({format_submit_time(first_ts)} 제출)\n"
                f"🏃 *오늘의 막차 탑승객*: <@{last_id}> 님 ({format_submit_time(last_ts)} 제출 ㄷㄷ)"
            )

        if approved_exemptions:
            title = f"✅ *[{yesterday_str} 분량] 마감 완료* ✅"
            body = "인증 제출과 면제권 사용 확인이 모두 끝났습니다!"
        else:
            title = f"🎉 *[{yesterday_str} 분량] 전원 제출 완료!* 🎉"
            body = "모두 고생 많으셨습니다! 오늘 하루도 화이팅입니다 💪"

        new_bomb = min(bomb_amount + BOMB_STEP, BOMB_MAX)
        new_effective = calc_effective_bomb(new_bomb)
        state["bomb_amount"] = new_bomb
        state_dirty = True
        if new_effective > effective_bomb:
            bomb_notice = f"\n\n💣 *폭탄 돌리기*: {effective_bomb:,}원 → *{new_effective:,}원* (+{new_effective - effective_bomb:,}원 누적)"
        elif new_effective >= BOMB_MAX:
            bomb_notice = f"\n\n💣 *폭탄 돌리기*: 상한액 *{new_effective:,}원* 도달! 터질 준비 완료 🔥"
        else:
            bomb_notice = f"\n\n💣 *폭탄 돌리기*: 연속 전원 제출 시작! 현재 *{new_effective:,}원*"
        print(f"[폭탄] 전원 제출 → 폭탄 {bomb_amount}원 → {new_bomb}원 (실효 {new_effective}원)")

        if state_dirty:
            save_state(state, state_sha)

        cheer_text = title + "\n" + body + submission_highlight + exemption_summary + bomb_notice + master_block
        requests.post("https://slack.com/api/chat.postMessage", headers=headers,
                      data={"channel": CHANNEL_ID, "text": cheer_text})
        print("전원 처리 완료. 결과 메시지 전송!")
        return

    # 미제출자가 있을 때 — 폭탄 돌리기 + 상습범 가중처벌 계산
    missing_uids = [
        uid for uid in MEMBERS
        if uid not in submitted_users and uid not in approved_exemption_users
    ]
    triggered_bomb_total = calc_triggered_bomb_total(bomb_amount, len(missing_uids))
    per_missing_floor = len(missing_uids) * BOMB_STEP
    penalties, new_miss_counts = calc_fines(missing_uids, miss_counts)

    penalty_lines = []
    for uid in missing_uids:
        name = MEMBERS.get(uid, uid)
        new_count = new_miss_counts[name]
        penalty = penalties[uid]
        if penalty > 0:
            penalty_lines.append(f"  • <@{uid}> ({name}): +{penalty:,}원 추가 [{new_count}번째 미제출]")
        else:
            penalty_lines.append(f"  • <@{uid}> ({name}): 0원 [첫 번째 미제출]")

    state["bomb_amount"] = 0
    state_dirty = True
    for name, cnt in new_miss_counts.items():
        state["miss_counts"][name] = cnt
    if state_dirty:
        save_state(state, state_sha)

    penalty_text = "\n".join(penalty_lines)
    bomb_floor_note = ""
    if triggered_bomb_total > effective_bomb:
        bomb_floor_note = f"\n(하한 적용: 미제출자 {len(missing_uids)}명 × 1,000원 = {per_missing_floor:,}원)"

    result_text = (
        f"🚨 *[{yesterday_str} 분량] 인증 마감* 🚨\n"
        f"마감 시간(08:59)이 지났습니다. 벌금 입금 부탁드립니다!\n"
        f"카카오뱅크 `3333-32-8918252`\n\n"
        f"💣 *최종 폭탄 금액: {triggered_bomb_total:,}원* — 미제출자끼리 합산 납부 (n빵 or 몰아주기 자율)"
        f"{bomb_floor_note}\n"
        f"(폭탄 초기화 → 1,000원)"
        + exemption_summary
        + "\n\n⚠️ *상습범 가중처벌* (개인별 추가 납부):\n"
        + penalty_text
        + master_block
    )
    requests.post("https://slack.com/api/chat.postMessage", headers=headers,
                  data={"channel": CHANNEL_ID, "text": result_text})
    print(f"검사 및 독촉 알림 전송 완료! 폭탄 {bomb_amount}원 / 최종 청구 {triggered_bomb_total}원 → 초기화, 미제출 {missing_uids}")

if __name__ == "__main__":
    check_and_notify()
