import os
import requests
from datetime import datetime
import pytz
from config import FULL_EXEMPT_DATES

# 1. 깃허브 시크릿(환경 변수) 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

# 2. 한국 시간(KST) 기준으로 오늘 날짜 구하기
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
today = now.date()
today_str = now.strftime("%m월 %d일")

# 3. 슬랙으로 보낼 메시지
full_exempt_reason = FULL_EXEMPT_DATES.get(today)
if full_exempt_reason:
    message = (
        f"📋 *[{today_str}] 오늘의 인증!*\n"
        f"오늘은 *전원 면제일* 입니다 — {full_exempt_reason}\n"
        f"제출 의무 없음! 원하시는 분은 자유롭게 인증해 주세요. 😊"
    )
else:
    message = (
        f"🔥 *[{today_str}] 오늘의 인증!*\n"
        f"여기에 스레드(댓글)로 오늘 푼 알고리즘을 인증해 주세요!\n\n"
        f"💡 면제권 사용 시 이미지 첨부 없이 댓글에 `면제권 사용(사유: ...)` 형식으로 작성해 주세요."
    )

# 4. Tetz봇 토큰을 이용해 메시지 전송
url = "https://slack.com/api/chat.postMessage"
headers = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/x-www-form-urlencoded"
}
payload = {
    "channel": CHANNEL_ID,
    "text": message
}

response = requests.post(url, headers=headers, data=payload)

if response.status_code == 200 and response.json().get("ok"):
    print("Tetz봇으로 아침 알림 전송 완료!")
else:
    print(f"전송 실패: {response.text}")