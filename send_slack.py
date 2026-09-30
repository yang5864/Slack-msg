from datetime import datetime
from zoneinfo import ZoneInfo

from config import FULL_EXEMPT_DATES, SERVICE_END_DATE, STUDY_START_DATE
from slack_utils import post_message


KST = ZoneInfo("Asia/Seoul")


def build_morning_message(today):
    today_str = today.strftime("%m월 %d일")
    exempt_reason = FULL_EXEMPT_DATES.get(today)

    if exempt_reason:
        return (
            f"📋 *[{today_str}] 오늘의 인증!*\n"
            f"오늘은 *전원 면제일*입니다 — {exempt_reason}\n"
            "제출 의무는 없으며, 원하시는 분은 자유롭게 인증해 주세요. 😊"
        )

    return (
        f"🔥 *[{today_str}] 오늘의 인증!*\n"
        "이 스레드에 오늘 푼 알고리즘 문제의 인증 이미지를 올려 주세요!\n\n"
        "💡 면제권은 횟수 제한 없이 사용할 수 있습니다. "
        "이미지 대신 `면제권 사용(사유: ...)` 형식으로 댓글을 남겨 주세요."
    )


def send_morning_message(now=None):
    now = now or datetime.now(KST)
    today = now.date()

    if today < STUDY_START_DATE:
        print(f"2기 시작일({STUDY_START_DATE}) 전이므로 아침 알림을 보내지 않습니다.")
        return
    if SERVICE_END_DATE and today >= SERVICE_END_DATE:
        print(f"2기 종료일({SERVICE_END_DATE}) 이후이므로 아침 알림을 보내지 않습니다.")
        return

    post_message(build_morning_message(today))
    print("2기 아침 인증글 전송 완료!")


if __name__ == "__main__":
    send_morning_message()
