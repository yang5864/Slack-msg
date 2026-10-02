"""멤버별 누적 벌금액을 GitHub 저장소에 보관한다."""

import base64
import json
import os

from config import FIXED_FINE_AMOUNT, MEMBERS


STATE_PATH = "miss_counts.v2.json"


def _github_context():
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        raise RuntimeError("벌금액 기록에는 GITHUB_TOKEN과 GITHUB_REPOSITORY가 필요합니다.")
    return token, repository


def _state_url(repository):
    return f"https://api.github.com/repos/{repository}/contents/{STATE_PATH}"


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def load_amounts():
    import requests

    token, repository = _github_context()
    response = requests.get(_state_url(repository), headers=_headers(token), timeout=20)
    response.raise_for_status()
    payload = response.json()
    amounts = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
    if not isinstance(amounts, dict) or any(
        not isinstance(name, str) or type(amount) is not int or amount < 0
        or amount % FIXED_FINE_AMOUNT != 0
        for name, amount in amounts.items()
    ):
        raise ValueError("벌금액 기록 형식이 올바르지 않습니다.")
    return amounts, payload["sha"]


def _already_recorded(target_date, names):
    """금액 파일에는 날짜를 두지 않고 GitHub 커밋 기록으로 재실행을 판별한다."""
    import requests

    token, repository = _github_context()
    date_key = target_date.isoformat()
    marker = f"Record study fines for {date_key}: "
    legacy_marker = f"Record study misses for {date_key}"
    page = 1
    while True:
        response = requests.get(
            f"https://api.github.com/repos/{repository}/commits",
            headers=_headers(token),
            params={"path": STATE_PATH, "since": f"{date_key}T00:00:00Z", "per_page": 100, "page": page},
            timeout=20,
        )
        response.raise_for_status()
        commits = response.json()
        for commit in commits:
            message = commit["commit"]["message"].split("\n", 1)[0]
            if message.startswith(marker):
                recorded_names = message[len(marker):].split(", ")
                if recorded_names != names:
                    raise RuntimeError(f"{date_key} 검사 결과가 기존 벌금 기록과 다릅니다. 수동 확인이 필요합니다.")
                return True
            if message == legacy_marker:
                return True
        if len(commits) < 100:
            return False
        page += 1


def record_misses(target_date, missing_user_ids):
    """미제출자마다 1,000원을 더하고 같은 날짜의 재실행은 중복 가산하지 않는다."""
    names = sorted(MEMBERS[user_id] for user_id in missing_user_ids)
    if names and _already_recorded(target_date, names):
        return load_amounts()[0]

    amounts, sha = load_amounts()
    if not names:
        return amounts

    for name in names:
        amounts[name] = amounts.get(name, 0) + FIXED_FINE_AMOUNT

    import requests

    token, repository = _github_context()
    content = base64.b64encode(
        (json.dumps(amounts, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    ).decode("ascii")
    response = requests.put(
        _state_url(repository),
        headers=_headers(token),
        json={
            "message": f"Record study fines for {target_date.isoformat()}: {', '.join(names)}",
            "content": content,
            "sha": sha,
        },
        timeout=20,
    )
    response.raise_for_status()
    return amounts
