"""2기 날짜별 미제출 기록을 GitHub 저장소에 보관한다."""

import base64
import json
import os
from collections import Counter


STATE_PATH = "miss_counts.v2.json"


def _github_context():
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        raise RuntimeError("미제출 횟수 기록에는 GITHUB_TOKEN과 GITHUB_REPOSITORY가 필요합니다.")
    return token, repository


def _state_url(repository):
    return f"https://api.github.com/repos/{repository}/contents/{STATE_PATH}"


def load_records():
    import requests

    token, repository = _github_context()
    response = requests.get(
        _state_url(repository),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    state = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
    records = state["missed_dates"]
    if not isinstance(records, dict):
        raise ValueError("미제출 기록 형식이 올바르지 않습니다.")
    return records, payload["sha"]


def count_misses(records):
    counts = Counter()
    for user_ids in records.values():
        counts.update(user_ids)
    return counts


def record_misses(target_date, missing_user_ids):
    """동일 날짜는 한 번만 반영한다. 저장 실패 시 알림도 보내지 않는다."""
    records, sha = load_records()
    date_key = target_date.isoformat()
    missing = sorted(missing_user_ids)
    if date_key in records:
        if sorted(records[date_key]) != missing:
            raise RuntimeError(f"{date_key} 미제출 기록과 현재 검사 결과가 다릅니다. 수동 확인이 필요합니다.")
        return count_misses(records)

    records[date_key] = missing
    import requests

    token, repository = _github_context()
    content = base64.b64encode(
        (json.dumps({"missed_dates": records}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    ).decode("ascii")
    response = requests.put(
        _state_url(repository),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={
            "message": f"Record study misses for {date_key}",
            "content": content,
            "sha": sha,
        },
        timeout=20,
    )
    response.raise_for_status()
    return count_misses(records)
