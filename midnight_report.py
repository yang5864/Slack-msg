import os
import requests
from datetime import datetime, timedelta
import pytz

# 1. 환경 변수 및 멤버 명단 (기존과 동일)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
MEMBERS = {
    "U0AE555JADP": "강채연", "U0AGDKJC6AW": "강태규", "U0ADY543QDB": "권유현",
    "U0AEWFJQL8G": "김건우", "U0AJGEDB9MJ": "김기선", "U0AEFT40BEV": "김수현",
    "U0AH924BYKS": "송준수", "U0AE6JC1V36": "양승환", "U0ADRBPLLNS": "오진호",
    "U0AH7L3FUTX": "이대주", "U0AGSGX5QCX": "이민호", "U0AE5BQ0VFB": "이아영",
    "U0AE7MCEA2H": "이지민", "U0ADXE54A92": "이채연", "U0AE5DKQF3K": "장지연",
    "U0AE589NP6G": "최규진", "U0AJGDB6W9G": "최보윤", "U0ADSS3M1HQ": "홍상우",
    "U0AFNU32D8T": "황지원",
}

kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
# 자정(00:00)에 실행되므로 now는 이미 다음 날 → 하루 빼서 인증 글이 올라온 날짜를 구함
today = now - timedelta(days=1)
today_str = today.strftime("%m월 %d일")

# 오늘 오전 9시 이후 메시지만 탐색 (범위 제한으로 limit 부족 방지)
today_9am = today.replace(hour=9, minute=0, second=0, microsecond=0)
oldest_ts = str(today_9am.timestamp())

headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}

def send_midnight_report():
    # Step A: 오늘 오전 9시에 올라온 인증글 찾기
    res_history = requests.get("https://slack.com/api/conversations.history",
                               headers=headers, params={"channel": CHANNEL_ID, "limit": 200, "oldest": oldest_ts}).json()
    
    target_ts = None
    if res_history.get("ok"):
        for msg in res_history["messages"]:
            if today_str in msg.get("text", "") and "오늘의 인증!" in msg.get("text", ""):
                target_ts = msg["ts"]
                break

    if not target_ts:
        print(f"{today_str} 인증 글을 찾지 못했습니다.")
        return

    # Step B: 스레드 댓글(제출자) 수집
    res_replies = requests.get("https://slack.com/api/conversations.replies", 
                               headers=headers, params={"channel": CHANNEL_ID, "ts": target_ts}).json()
    
    submitted_names = []
    if res_replies.get("ok"):
        for reply in res_replies["messages"]:
            if reply["ts"] == target_ts: continue
            user_id = reply.get("user")
            if user_id in MEMBERS:
                submitted_names.append(MEMBERS[user_id])

    # 중복 제거 및 정렬
    submitted_names = sorted(list(set(submitted_names)))
    count = len(submitted_names)

    # Step C: 메시지 구성 및 전송 (채널로 바로 발송!)
    if count == len(MEMBERS):
        result_text = (
            f"🎉 *[{today_str} 분량] 전원 인증 완료 (조기 종료)* 🎉\n"
            f"모든 분들이 자정 전에 제출을 완료하셨습니다! 폼 미쳤다! 👏\n"
            f"내일 아침 마감 알림은 생략됩니다. 모두 푹 주무세요! 🌙"
        )
    else:
        result_text = (
            f"🌙 *[{today_str} 분량] 인증 중간 점검 (자정)* 🌙\n"
            f"현재까지 총 *{count}명* 제출하셨습니다!\n\n"
            f"✅ *제출자 명단:*\n{', '.join(submitted_names) if submitted_names else '아직 없습니다 🥲'}\n\n"
            f"⏰ 마감까지 9시간 남았습니다. 아직 안 하신 분들은 서둘러주세요! 🔥"
        )

    requests.post("https://slack.com/api/chat.postMessage",
                  headers=headers, data={"channel": CHANNEL_ID, "text": result_text})

if __name__ == "__main__":
    send_midnight_report()