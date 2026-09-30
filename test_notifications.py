"""운영 인증글과 분리된 일회성 Slack 발송 테스트."""

from slack_utils import TEST_MESSAGE_MARKER, post_message


TEST_MESSAGES = (
    (
        "아침 인증 알림",
        "🔥 인증글 예시입니다. 오늘 푼 알고리즘 문제의 인증 이미지를 스레드에 올리는 흐름을 안내합니다.",
    ),
    (
        "자정 중간 점검",
        "🌙 중간 점검 예시입니다. 제출 현황과 다음날 오전 9시 9분 마감 안내가 이곳에 표시됩니다.",
    ),
    (
        "다음날 미제출 검사",
        "🚨 검사 결과 예시입니다. 실제 미제출자 판정이나 벌금 부과는 하지 않습니다. "
        "운영 시 미제출자 1인당 벌금은 1,000원입니다.",
    ),
)


def send_test_notifications():
    for label, body in TEST_MESSAGES:
        text = f"{TEST_MESSAGE_MARKER} *{label}*\n{body}\n_테스트 전용 · 제출/벌금 처리 대상 아님_"
        post_message(text)
        print(f"테스트 전송 완료: {label}")


if __name__ == "__main__":
    send_test_notifications()
