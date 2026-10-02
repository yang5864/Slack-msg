import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import (
    FIXED_FINE_AMOUNT,
    FULL_EXEMPT_DATES,
    MEMBERS,
    REJECT_EXEMPTION_REASON_KEYWORDS,
    SERVICE_END_DATE,
    STUDY_START_DATE,
    VALID_EXEMPTION_REASON_KEYWORDS,
    active_members,
)
from miss_tracker import record_misses
from slack_utils import channel_history, has_image, is_test_message, post_message, thread_replies


KST = ZoneInfo("Asia/Seoul")


def extract_exemption_reason(text: str):
    """면제권 댓글이면 사유 문자열을, 아니면 None을 반환한다."""
    normalized = " ".join((text or "").split())
    if "면제권" not in normalized:
        return None

    reason = re.sub(r"면제권\s*[가-힣a-zA-Z]*[.。,]?\s*", "", normalized)
    reason = re.sub(r"사유\s*[:：-]?\s*", "", reason)
    return reason.strip(" ():-")


def judge_exemption_reason(reason: str):
    """1기와 같은 사유 기준을 적용한다. 사용 횟수 제한은 없다."""
    trimmed = (reason or "").strip()
    if len(trimmed) < 2:
        return False, "사유가 비어 있거나 너무 짧아요"

    normalized = re.sub(r"\s+", "", trimmed).lower()
    if any(keyword in normalized for keyword in REJECT_EXEMPTION_REASON_KEYWORDS):
        return False, "개인 여가성 사유는 자동 승인 대상이 아니에요"
    if any(keyword in normalized for keyword in VALID_EXEMPTION_REASON_KEYWORDS):
        return True, "합당한 사유로 판단했어요"
    return False, "질병·시험·공적 일정 계열 사유로 보기 어려워 자동 승인하지 않았어요"


def format_submit_time(timestamp: float, target_date) -> str:
    submitted_at = datetime.fromtimestamp(timestamp, tz=KST)
    day_label = "어제" if submitted_at.date() == target_date else "오늘"
    ampm = "오전" if submitted_at.hour < 12 else "오후"
    hour = submitted_at.hour % 12 or 12
    minute = f" {submitted_at.minute}분" if submitted_at.minute else ""
    return f"{day_label} {ampm} {hour}시{minute}"


def build_exemption_summary(approved, rejected):
    sections = []
    if approved:
        lines = [f"  • <@{item['user_id']}>: {item['reason']}" for item in approved]
        sections.append("\n\n🎟️ *면제권 승인 (횟수 제한 없음)*\n" + "\n".join(lines))
    if rejected:
        lines = [
            f"  • <@{item['user_id']}>: {item['reason'] or '사유 미기재'} — {item['note']}"
            for item in rejected
        ]
        sections.append("\n\n⚠️ *면제권 미승인*\n" + "\n".join(lines))
    return "".join(sections)


def build_cumulative_fine_summary(miss_counts):
    lines = [
        f"  • <@{user_id}> ({name}): {miss_counts.get(user_id, 0)}회 · "
        f"*{miss_counts.get(user_id, 0) * FIXED_FINE_AMOUNT:,}원*"
        for user_id, name in MEMBERS.items()
    ]
    total = sum(miss_counts.values()) * FIXED_FINE_AMOUNT
    return (
        "\n\n📒 *누적 벌금 현황*\n"
        + "\n".join(lines)
        + f"\n*전체 누적 벌금액: {total:,}원*"
    )


def check_and_notify(now=None):
    now = now or datetime.now(KST)
    target = (now - timedelta(days=1)).date()
    target_str = target.strftime("%m월 %d일")

    if target < STUDY_START_DATE:
        print(f"2기 시작일({STUDY_START_DATE}) 전 분량이므로 검사를 생략합니다.")
        return
    if SERVICE_END_DATE and target >= SERVICE_END_DATE:
        print(f"2기 종료일({SERVICE_END_DATE}) 이후 분량이므로 검사를 생략합니다.")
        return

    members = active_members(target)

    target_9am = datetime.combine(target, datetime.min.time(), tzinfo=KST).replace(hour=9)
    messages = [
        message for message in channel_history(str(target_9am.timestamp()))
        if not is_test_message(message)
    ]

    if any(
        f"[{target_str} 분량]" in message.get("text", "")
        and any(
            marker in message.get("text", "")
            for marker in ("인증 마감", "전원 제출 완료", "마감 완료", "전원 면제일")
        )
        for message in messages
    ):
        print(f"{target_str} 마감 결과가 이미 전송되어 중복 실행을 생략합니다.")
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

    submitted_at = {}
    token_requests = {}
    for reply in thread_replies(parent["ts"]):
        if reply.get("ts") == parent["ts"]:
            continue
        user_id = reply.get("user")
        if user_id not in members:
            continue

        reply_ts = float(reply["ts"])
        if has_image(reply):
            submitted_at[user_id] = min(reply_ts, submitted_at.get(user_id, reply_ts))

        reason = extract_exemption_reason(reply.get("text", ""))
        if reason is not None:
            token_requests[user_id] = {"reason": reason, "ts": reply_ts}

    approved = []
    rejected = []
    exempt_users = set()
    for user_id, request in sorted(token_requests.items(), key=lambda item: item[1]["ts"]):
        if user_id in submitted_at:
            continue
        accepted, note = judge_exemption_reason(request["reason"])
        item = {"user_id": user_id, "reason": request["reason"], "note": note}
        if accepted:
            exempt_users.add(user_id)
            approved.append(item)
        else:
            rejected.append(item)

    exemption_summary = build_exemption_summary(approved, rejected)

    if target in FULL_EXEMPT_DATES:
        miss_counts = record_misses(target, [])
        post_message(
            f"📋 *[{target_str} 분량] 전원 면제일*\n"
            f"{FULL_EXEMPT_DATES[target]} — 벌금 없이 마감합니다."
            + build_cumulative_fine_summary(miss_counts)
        )
        print(f"{target_str} 전원 면제일 마감 안내 완료.")
        return

    missing = [
        user_id for user_id in members
        if user_id not in submitted_at and user_id not in exempt_users
    ]
    miss_counts = record_misses(target, missing)
    cumulative_summary = build_cumulative_fine_summary(miss_counts)

    if not missing:
        ranked = sorted(submitted_at.items(), key=lambda item: item[1])
        highlight = ""
        if len(ranked) == 1:
            user_id, timestamp = ranked[0]
            highlight = f"\n\n🥇 *오늘의 인증자*: <@{user_id}> ({format_submit_time(timestamp, target)} 제출)"
        elif ranked:
            first_id, first_ts = ranked[0]
            last_id, last_ts = ranked[-1]
            highlight = (
                f"\n\n🥇 *오늘의 얼리버드*: <@{first_id}> ({format_submit_time(first_ts, target)} 제출)\n"
                f"🏃 *오늘의 막차 탑승객*: <@{last_id}> ({format_submit_time(last_ts, target)} 제출)"
            )

        title = "마감 완료" if approved else "전원 제출 완료"
        text = (
            f"🎉 *[{target_str} 분량] {title}!* 🎉\n"
            "모두 고생 많으셨습니다! 오늘 하루도 화이팅입니다 💪"
            + highlight
            + exemption_summary
            + cumulative_summary
        )
    else:
        fine_lines = [
            f"  • <@{user_id}> ({members[user_id]}): 이번 *{FIXED_FINE_AMOUNT:,}원*"
            for user_id in missing
        ]
        total = len(missing) * FIXED_FINE_AMOUNT
        text = (
            f"🚨 *[{target_str} 분량] 인증 마감* 🚨\n"
            "마감 시간(오전 9시 9분)이 지났습니다.\n\n"
            f"💸 *이번 미제출 기록: 1인당 {FIXED_FINE_AMOUNT:,}원*\n"
            + "\n".join(fine_lines)
            + f"\n\n이번 발생액 합계: *{total:,}원*\n"
            "지금 송금하지 않아도 됩니다. 미제출 횟수를 기록해 두었다가 "
            "추후 회식·모임 비용을 나눌 때 한 번에 정산할게요."
            + exemption_summary
            + cumulative_summary
        )

    post_message(text)
    print(f"{target_str} 검사 완료. 제출 {len(submitted_at)}명, 면제 {len(exempt_users)}명, 미제출 {len(missing)}명.")


if __name__ == "__main__":
    check_and_notify()
