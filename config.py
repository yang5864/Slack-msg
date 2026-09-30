from datetime import date


# 2기 운영 설정
SLACK_CHANNEL_ID = "C0C562P5YK0"
STUDY_START_DATE = date(2026, 10, 1)
SERVICE_END_DATE = None  # 종료일이 정해지면 date(YYYY, M, D)로 변경
FIXED_FINE_AMOUNT = 1_000

# Slack ID가 확인된 인원만 자동 검사 대상에 포함한다.
MEMBERS = {
    "U0BGQCYEUD6": "양승환",
    "U0C5C6M0GQH": "김건우",
    "U0C5FH37PL4": "이지민",
    "U0C64JTD2TA": "이대주",
    "U0C64JQ3QRE": "권유현",
    "U0C5C69MPKK": "송준수",
    "U0C5A3T04UA": "오진호",
}

# Slack 참여 후 ID를 MEMBERS에 옮긴다.
PENDING_MEMBERS = ("김수현", "홍상우")

# 2026년 10~12월 평일 공휴일. 주말은 정기 검사 대상이 아니므로 제외한다.
FULL_EXEMPT_DATES = {
    date(2026, 10, 5): "개천절 대체공휴일",
    date(2026, 10, 9): "한글날",
    date(2026, 12, 25): "성탄절",
}

# 사유 심사 규칙은 1기와 동일하게 유지하되, 사용 횟수 제한은 없다.
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
