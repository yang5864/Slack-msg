import os
import requests
from datetime import datetime
import pytz

# 1. 깃허브 시크릿(환경 변수) 가져오기
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

# 2. 한국 시간(KST) 기준으로 오늘 날짜 구하기
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
today_str = now.strftime("%m월 %d일")

# 3. 슬랙으로 보낼 메시지
message = f"🔥 *[{today_str}] 오늘의 인증!*\n여기에 스레드(댓글)로 오늘 푼 알고리즘을 인증해 주세요!"

# 4. 알고봇 토큰을 이용해 메시지 전송
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
    print("알고봇으로 아침 알림 전송 완료!")
else:
    print(f"전송 실패: {response.text}")