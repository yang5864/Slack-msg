import requests
import datetime
import os

# 1. 한국 시간(KST) 기준으로 오늘 날짜 구하기
now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
today_str = now.strftime("%m월 %d일")

# 2. 슬랙으로 보낼 메시지 (스레드 유도를 위해 깔끔하게 작성)
message = f"🔥 *[{today_str}] 오늘의 인증!* 여기에 스레드(댓글)로 오늘 푼 알고리즘을 인증해 주세요!"

# 3. 슬랙 웹훅으로 전송
webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
payload = {"text": message}
requests.post(webhook_url, json=payload)