import os

from config import SLACK_CHANNEL_ID


SLACK_API_BASE = "https://slack.com/api"


def get_channel_id() -> str:
    return SLACK_CHANNEL_ID


def _headers() -> dict[str, str]:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN 환경변수가 없습니다.")
    return {"Authorization": f"Bearer {token}"}


def slack_get(method: str, **params):
    import requests

    response = requests.get(
        f"{SLACK_API_BASE}/{method}",
        headers=_headers(),
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API {method} 실패: {payload.get('error', 'unknown_error')}")
    return payload


def post_message(text: str):
    import requests

    response = requests.post(
        f"{SLACK_API_BASE}/chat.postMessage",
        headers=_headers(),
        data={"channel": get_channel_id(), "text": text},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack 메시지 전송 실패: {payload.get('error', 'unknown_error')}")
    return payload


def channel_history(oldest_ts: str):
    return slack_get(
        "conversations.history",
        channel=get_channel_id(),
        limit=200,
        oldest=oldest_ts,
    )["messages"]


def thread_replies(thread_ts: str):
    return slack_get(
        "conversations.replies",
        channel=get_channel_id(),
        ts=thread_ts,
        limit=100,
    )["messages"]


def has_image(reply: dict) -> bool:
    return any(
        item.get("mimetype", "").startswith("image/")
        for item in reply.get("files", [])
    )
