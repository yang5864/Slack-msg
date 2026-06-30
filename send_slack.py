import os
import requests
from datetime import datetime
import pytz
from config import FULL_EXEMPT_DATES, FAREWELL_DATE

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
monthly_reset_notice = ""
if today.day == 1:
    monthly_reset_notice = "\n\n🎟️ 이번 달 면제권이 1개로 초기화되었습니다."

if today == FAREWELL_DATE:
    message = (
        f"🎓 *[{today_str}] 오늘의 인증!*\n"
        f"테츠봇을 만든게 엊그제 같은데...\n\n"
        f"벌써 내일이면 최종 프로젝트 기간이 시작됩니다.\n\n"
        f"그동안 함께 달려온 모든 분들, 정말 수고 많으셨습니다!\n"
        f"뿔뿔이 흩어지더라도 각자의 자리에서 멋진 개발자로 성장하시길 응원할게요!\n\n"
        f"계속 진행하길 희망하신 분들과 스터디는 계속됩니다! 남은 분들, 앞으로도 함께 달려봐요!\n\n"
        f"그리고... 오늘은 마지막이니까... 벌금 없는 자유 제출일입니다..! 원하시는 분들은 자유롭게 인증해 주세요!\n\n"
        f"모두 고생 많으셨습니다! 26회차 화이팅!\n\n"
        f"-Tetz Bot 개발자, 양승환 드림-"
        f"{monthly_reset_notice}"
    )
elif full_exempt_reason:
    message = (
        f"📋 *[{today_str}] 오늘의 인증!*\n"
        f"오늘은 *전원 면제일* 입니다 — {full_exempt_reason}\n"
        f"제출 의무 없음! 원하시는 분은 자유롭게 인증해 주세요. 😊"
        f"{monthly_reset_notice}"
    )
else:
    message = (
        f"🔥 *[{today_str}] 오늘의 인증!*\n"
        f"여기에 스레드(댓글)로 오늘 푼 알고리즘을 인증해 주세요!\n\n"
        f"💡 면제권 사용 시 이미지 첨부 없이 댓글에 `면제권 사용(사유: ...)` 형식으로 작성해 주세요."
        f"{monthly_reset_notice}"
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
