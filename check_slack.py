import os
import requests
from datetime import datetime, timedelta
import pytz

# 1. 깃허브 시크릿(환경 변수)에서 토큰과 채널 ID 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

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

# API 요청 시 사용할 공통 헤더
headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/x-www-form-urlencoded"
}

def format_submit_time(ts: float) -> str:
    """unix timestamp → '어제 오후 2시' / '오늘 오전 8시 58분' 형식"""
    dt = datetime.fromtimestamp(ts, tz=kst)
    if dt.date() == yesterday.date():
        day_label = "어제"
    else:
        day_label = "오늘"
    ampm = "오전" if dt.hour < 12 else "오후"
    hour = dt.hour if dt.hour <= 12 else dt.hour - 12
    if dt.minute == 0:
        return f"{day_label} {ampm} {hour}시"
    return f"{day_label} {ampm} {hour}시 {dt.minute}분"


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
            # 메시지 내용 중에 "오늘의 인증!" 이라는 키워드가 있으면 부모 글로 인식
            if "오늘의 인증!" in msg.get("text", "") and yesterday_str in msg.get("text", ""):
                target_ts = msg["ts"]
                break

    if not target_ts:
        print("오늘의 인증 글을 찾지 못했습니다.")
        return

    # Step B: 찾은 부모 메시지에 달린 스레드(댓글) 목록 가져오기
    url_replies = "https://slack.com/api/conversations.replies"
    params_replies = {
        "channel": CHANNEL_ID,
        "ts": target_ts
    }

    res_replies = requests.get(url_replies, headers=headers, params=params_replies).json()

    submitted_users = set()
    replies_with_ts = []  # (ts, user_id) 튜플 리스트
    if res_replies.get("ok"):
        for reply in res_replies["messages"]:
            # 부모 메시지 자체는 제외하고, 댓글 단 사람들의 ID만 수집
            if reply["ts"] == target_ts:
                continue
            user_id = reply.get("user")
            if user_id:
                submitted_users.add(user_id)
                replies_with_ts.append((float(reply["ts"]), user_id))

    # Step C: 스터디원 전체 명단과 비교하여 미제출자 색출
    missing_users = []
    for user_id, name in MEMBERS.items():
        if user_id not in submitted_users:
            missing_users.append(f"<@{user_id}>")

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
            f"🏃‍♂️ *오늘의 막차 탑승객*: <@{last_id}> 님 ({format_submit_time(last_ts)} 제출 ㄷㄷ)"
        )
        requests.post("https://slack.com/api/chat.postMessage", headers=headers, data={"channel": CHANNEL_ID, "text": cheer_text})
        print("전원 제출 확인 완료. 격려 메시지 전송!")
        return
    
    # 미제출자가 있을 때만 독촉 발송
    mentions = ", ".join(missing_users)
    result_text = f"🚨 *[{yesterday_str} 분량] 인증 마감* 🚨\n{mentions} 님, 마감 시간(09:00)이 지났습니다. 벌금 입금 부탁드립니다! \n카카오뱅크 `3333-32-8918252`"

    requests.post("https://slack.com/api/chat.postMessage", headers=headers, data={"channel": CHANNEL_ID, "text": result_text})
    print("검사 및 독촉 알림 전송 완료!")

if __name__ == "__main__":
    check_and_notify()