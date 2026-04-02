import os
import re
import requests
import time
import concurrent.futures
from datetime import datetime, timedelta
import pytz
import google.generativeai as genai
from PIL import Image
from io import BytesIO
import json

# 1. 깃허브 시크릿(환경 변수)에서 토큰과 채널 ID 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')

# 2. 스터디원 19명 명단 (여기에 아까 메모해둔 ID와 이름을 채워주세요!)
MEMBERS = {
    "U0AE555JADP": "강채연",
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

# Solved.ac 티어 변환 테이블
# level 1-5: 브론즈 5~1 / 6-10: 실버 5~1 / 11-15: 골드 5~1
# 16-20: 플래티넘 5~1 / 21-25: 다이아 5~1 / 26-30: 루비 5~1
_TIER_KR = ["브론즈", "실버", "골드", "플래티넘", "다이아", "루비"]
_SCORE_RANGES = [(1, 20), (21, 40), (41, 70), (71, 90), (91, 97), (98, 100)]

def get_solved_ac_info(problem_id: int):
    """Solved.ac API로 백준 문제 실제 난이도 조회"""
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
            return {"tier_str": "Unrated", "converted_score": 5, "title": title}

        tier_idx = (level - 1) // 5       # 0=브론즈 ... 5=루비
        sub = 5 - ((level - 1) % 5)       # 5=쉬움, 1=어려움 (티어 내)
        tier_str = f"{_TIER_KR[tier_idx]} {sub}"

        base, top = _SCORE_RANGES[tier_idx]
        sub_pos = (level - 1) % 5         # 0=티어 내 최하, 4=티어 내 최상
        converted_score = round(base + (top - base) * sub_pos / 4)

        return {
            "tier_str": tier_str,
            "converted_score": converted_score,
            "title": title,
            "accepted_user_count": data.get("acceptedUserCount"),
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

def analyze_problem(data):
    """Gemini를 사용한 멀티모달 이미지 분석"""
    user_id, img_url = data
    try:
        response = requests.get(img_url, headers=img_headers)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))

        prompt = """
        너는 '1일 1알고 스터디'의 냉철한 AI 코딩테스트 난이도 판별사야.
        첨부된 화면 캡처 이미지를 보고 어느 플랫폼(백준, 프로그래머스, SW Expert Academy 등)의 무슨 문제인지 파악해.

        🚨 [절대 규칙: 환각(Hallucination) 금지!] 🚨
        1. 문제의 티어(난이도)를 너의 배경지식으로 절대 추측하거나 지어내지 마.
        2. 반드시 화면에 텍스트로 적혀 있는 티어(예: Silver III, 브론즈 1)나 아이콘의 색상을 있는 그대로 정확하게 읽어.
        3. 팩트 기반으로 확인된 티어만 'original_tier'에 적어.

        [난이도 통합 환산 기준 (1~100점)]
        두 플랫폼의 난이도를 공정하게 비교하기 위해 아래 기준을 따라 절대 점수를 부여해.
        - 1~20점: 백준 브론즈 / 프로그래머스 Lv.1 (입문자)
        - 21~40점: 백준 실버 / 프로그래머스 Lv.2 (기본기)
        - 41~70점: 백준 골드 / 프로그래머스 Lv.3 (실전 코테 수준)
        - 71~90점: 백준 플래티넘 / 프로그래머스 Lv.4 (고수)
        - 91~100점: 백준 다이아, 루비 / 프로그래머스 Lv.5 (신)
        * 같은 티어/레벨 안에서도 문제의 유명도나 체감 난이도를 고려해서 디테일하게 점수를 가감해.

        반드시 아래 JSON 형식으로만 대답해. 마크다운(```json) 없이 순수 JSON 텍스트만 출력해.
        {
        "platform": "백준 혹은 프로그래머스",
        "problem_name": "문제 이름 (번호 포함)",
        "original_tier": "골드 1, Lv.3 등 원본 플랫폼 기준 난이도",
        "converted_score": 75,
        "reason": "이 문제에 이 점수를 부여한 이유 (알고리즘 종류와 체감 난이도를 1문장으로 짧고 유쾌하게 설명)"
        }
        """
        res = model.generate_content([prompt, img])
        result = json.loads(res.text.strip().replace('```json', '').replace('```', '').strip())
        try:
            result['converted_score'] = int(str(result.get('converted_score', 0)).replace('점', '').strip())
        except ValueError:
            print(f"[경고] 제미나이가 이상한 점수를 줬습니다: {result.get('converted_score')}")
            result['converted_score'] = 0
        result['user_id'] = user_id

        # 백준이면 Solved.ac API로 실제 난이도 보정 (Gemini 환각 방지)
        # 프로그래머스는 공개 API 없으므로 Gemini 평가 그대로 사용
        if "백준" in result.get("platform", ""):
            problem_num = extract_boj_number(result.get("problem_name", ""))
            if problem_num:
                solved_info = get_solved_ac_info(problem_num)
                if solved_info:
                    result['original_tier'] = solved_info['tier_str']
                    result['converted_score'] = solved_info['converted_score']
                    result['accepted_user_count'] = solved_info['accepted_user_count']
                    if solved_info['title']:
                        result['problem_name'] = f"{solved_info['title']} ({problem_num}번)"
                    print(f"[Solved.ac] {problem_num}번 → {solved_info['tier_str']} ({solved_info['converted_score']}점, 정답자 {solved_info['accepted_user_count']}명)")

        name = MEMBERS.get(user_id, user_id)
        print(f"[분석 결과] {name}: {result.get('problem_name')} ({result.get('platform')} · {result.get('original_tier')}) → {result.get('converted_score')}점")
        return result
    except Exception as e:
        print(f"[Gemini 분석 실패] user={user_id}, error={e}")
        return None

def compare_with_gemini(a, b):
    """동점자 두 문제를 Gemini에게 직접 비교해 더 어려운 쪽 반환"""
    prompt = (
        f"다음 두 알고리즘 문제 중 어느 것이 더 어렵습니까?\n"
        f"문제 1: {a['problem_name']} ({a['platform']}, {a['original_tier']})\n"
        f"문제 2: {b['problem_name']} ({b['platform']}, {b['original_tier']})\n"
        f"반드시 '1' 또는 '2' 숫자 하나만 출력하세요."
    )
    try:
        res = model.generate_content(prompt)
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
    has_count = all(r.get("accepted_user_count") is not None for r in tied)

    if all_boj and has_count:
        winner = min(tied, key=lambda x: x["accepted_user_count"])
        print(f"[동점 처리] BOJ 정답자 수 기준 → {winner['problem_name']} ({winner['accepted_user_count']}명) 승")
        return winner

    print(f"[동점 처리] Gemini 토너먼트 ({len(tied)}명)")
    winner = tied[0]
    for challenger in tied[1:]:
        winner = compare_with_gemini(winner, challenger)
    return winner

def run_gemini_batch(tasks, batch_size=10):
    """RPM 5 제한을 고려해 batch_size씩 병렬 처리 후 60초 대기"""
    results = []
    total_batches = (len(tasks) + batch_size - 1) // batch_size
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"Gemini 배치 {batch_num}/{total_batches}: {len(batch)}명 분석 중...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            batch_results = list(executor.map(analyze_problem, batch))
        results.extend(batch_results)
        # 마지막 배치가 아니면 RPM 리셋 대기
        if i + batch_size < len(tasks):
            print("RPM 제한 대기 중... (61초)")
            time.sleep(61)
    return results

def check_and_notify():
    # Step A: 오늘 아침에 올라온 '오늘의 인증!' 부모 메시지 찾기
    url_history = "https://slack.com/api/conversations.history"
    params_history = {
        "channel": CHANNEL_ID,
        "limit": 200,
        "oldest": oldest_ts  # 어제 9시 이후 메시지만 탐색
    }

    res_history = requests.get(url_history, headers=headers, params=params_history).json()

    target_ts = None
    if res_history.get("ok"):
        for msg in res_history["messages"]:
            if "오늘의 인증!" in msg.get("text", "") and yesterday_str in msg.get("text", ""):
                target_ts = msg["ts"]
                break

    if not target_ts:
        print("오늘의 인증 글을 찾지 못했습니다.")
        return

    # Step B-0: midnight_report가 이미 조기 종료 선언했는지 확인
    # - "조기 종료" + yesterday_str 두 조건 모두 충족해야 유효 (다른 날짜 오탐 방지)
    # - 감지되면 생략이 아니라 Step D(전원 격려 메시지)로 이어짐
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
        "ts": target_ts
    }

    res_replies = requests.get(url_replies, headers=headers, params=params_replies).json()

    submitted_users = set()
    replies_with_ts = []   # (ts, user_id) 튜플 리스트
    user_images = {}       # user_id -> img_url (멤버당 첫 번째 이미지만)

    if res_replies.get("ok"):
        for reply in res_replies["messages"]:
            # 부모 메시지 자체는 제외하고, 댓글 단 사람들의 ID만 수집
            if reply["ts"] == target_ts:
                continue
            user_id = reply.get("user")
            if user_id and user_id in MEMBERS:
                submitted_users.add(user_id)
                replies_with_ts.append((float(reply["ts"]), user_id))
                # 이미지 첨부 수집 (멤버당 첫 번째 이미지만)
                if user_id not in user_images:
                    for f in reply.get("files", []):
                        if f.get("mimetype", "").startswith("image/"):
                            url = f.get("url_private_download") or f.get("url_private")
                            if url:
                                user_images[user_id] = url
                            break

    # Step C: 스터디원 전체 명단과 비교하여 미제출자 색출
    # already_closed == True 이면 자정에 전원 제출이 확인된 것이므로 미제출자 없음으로 처리
    if already_closed:
        missing_users = []
        print("자정 조기 종료 확인됨. 전원 제출로 처리.")
    else:
        missing_users = [
            f"<@{uid}>" for uid, name in MEMBERS.items()
            if uid not in submitted_users
        ]

    # Step D-0: Gemini 알고리즘 마스터 선정 (이미지를 첨부한 제출자 대상)
    master_block = ""
    analysis_tasks = list(user_images.items())  # [(user_id, img_url), ...]
    if analysis_tasks:
        print(f"Gemini 분석 시작: {len(analysis_tasks)}명")
        analysis_results = run_gemini_batch(analysis_tasks)
        valid_results = [r for r in analysis_results if r is not None]

        if valid_results:
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
            print(f"알고리즘 마스터 선정: {winner_name} ({best['converted_score']}점)")
        else:
            print("Gemini 분석 결과 없음. 마스터 선정 생략.")
    else:
        print("이미지 첨부 없음. 마스터 선정 생략.")

    # Step D: 결과에 따라 슬랙으로 메시지 전송
    if not missing_users:
        # 🌟 미제출자가 0명(전원 제출)이면 격려 + 최초/최후 제출자 칭호 메시지 발송
        replies_with_ts.sort(key=lambda x: x[0])
        first_ts, first_id = replies_with_ts[0]
        last_ts, last_id = replies_with_ts[-1]

        cheer_text = (
            f"🎉 *[{yesterday_str} 분량] 전원 제출 완료!* 🎉\n"
            f"모두 고생 많으셨습니다! 오늘 하루도 화이팅입니다 💪\n\n"
            f"🥇 *오늘의 얼리버드*: <@{first_id}> 님 ({format_submit_time(first_ts)} 제출)\n"
            f"🏃 *오늘의 막차 탑승객*: <@{last_id}> 님 ({format_submit_time(last_ts)} 제출 ㄷㄷ)"
            + master_block
        )
        requests.post("https://slack.com/api/chat.postMessage", headers=headers, data={"channel": CHANNEL_ID, "text": cheer_text})
        print("전원 제출 확인 완료. 격려 메시지 전송!")
        return

    # 미제출자가 있을 때 독촉 발송
    mentions = ", ".join(missing_users)
    result_text = (
        f"🚨 *[{yesterday_str} 분량] 인증 마감* 🚨\n"
        f"{mentions} 님, 마감 시간(08:59)이 지났습니다. 벌금 입금 부탁드립니다!\n"
        f"카카오뱅크 `3333-32-8918252`"
        + master_block
    )
    requests.post("https://slack.com/api/chat.postMessage", headers=headers, data={"channel": CHANNEL_ID, "text": result_text})
    print("검사 및 독촉 알림 전송 완료!")

if __name__ == "__main__":
    check_and_notify()
