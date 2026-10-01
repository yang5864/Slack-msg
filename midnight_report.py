from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import FULL_EXEMPT_DATES, SERVICE_END_DATE, STUDY_START_DATE, active_members
from slack_utils import channel_history, has_image, is_test_message, post_message, thread_replies


KST = ZoneInfo("Asia/Seoul")


def send_midnight_report(now=None):
    now = now or datetime.now(KST)
    target = (now - timedelta(days=1)).date()
    target_str = target.strftime("%m월 %d일")

    if target < STUDY_START_DATE:
        print(f"2기 시작일({STUDY_START_DATE}) 전 분량이므로 자정 리포트를 생략합니다.")
        return
    if SERVICE_END_DATE and target >= SERVICE_END_DATE:
        print(f"2기 종료일({SERVICE_END_DATE}) 이후 분량이므로 자정 리포트를 생략합니다.")
        return
    if target in FULL_EXEMPT_DATES:
        print(f"전원 면제일({target_str})이므로 자정 리포트를 생략합니다.")
        return

    members = active_members(target)

    target_9am = datetime.combine(target, datetime.min.time(), tzinfo=KST).replace(hour=9)
    messages = [
        message for message in channel_history(str(target_9am.timestamp()))
        if not is_test_message(message)
    ]

    if any(
        target_str in message.get("text", "")
        and ("인증 중간 점검 (자정)" in message.get("text", "") or "조기 종료" in message.get("text", ""))
        for message in messages
    ):
        print(f"{target_str} 자정 리포트가 이미 전송되어 중복 실행을 생략합니다.")
        return

    parent = next(
        (
            message for message in messages
            if target_str in message.get("text", "") and "오늘의 인증!" in message.get("text", "")
        ),
        None,
    )
    if not parent:
        print(f"{target_str} 인증글을 찾지 못했습니다.")
        return

    submitted = {
        reply.get("user")
        for reply in thread_replies(parent["ts"])
        if reply.get("ts") != parent["ts"]
        and reply.get("user") in members
        and has_image(reply)
    }
    submitted_names = sorted(members[user_id] for user_id in submitted)
    count = len(submitted)

    if count == len(members):
        text = (
            f"🎉 *[{target_str} 분량] 전원 인증 완료 (조기 종료)* 🎉\n"
            "모든 분이 자정 전에 제출을 완료했습니다! 👏\n"
            "다음날 오전에는 얼리버드와 막차 결과만 안내합니다. 모두 푹 주무세요! 🌙"
        )
    else:
        text = (
            f"🌙 *[{target_str} 분량] 인증 중간 점검 (자정)* 🌙\n"
            f"현재까지 총 *{count}/{len(members)}명* 제출했습니다.\n\n"
            f"✅ *제출자:* {', '.join(submitted_names) if submitted_names else '아직 없습니다 🥲'}\n\n"
            "⏰ 마감은 오전 9시 9분입니다. 아직 안 하신 분들은 서둘러 주세요! 🔥"
        )

    post_message(text)
    print(f"{target_str} 자정 리포트 전송 완료 ({count}/{len(members)}명).")


if __name__ == "__main__":
    send_midnight_report()
