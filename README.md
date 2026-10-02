# Tetz Bot — 알고리즘 스터디 2기

Slack 알고리즘 스터디의 인증글, 자정 현황, 다음날 마감 결과를 자동으로 안내하는 봇입니다.

- 2기 시작일: 2026-10-01
- Slack 채널: `C0C562P5YK0`
- 운영자·개발자: 양승환
- 1기 운영 기간: 2026-03-23 ~ 2026-08-26

## 운영 일정

모든 GitHub Actions 워크플로우는 자체 `schedule` 없이 cron-job.org의 `workflow_dispatch` 호출로 실행합니다.

| 시각(KST) | 스크립트 | 역할 |
|---|---|---|
| 00:00 | `midnight_report.py` | 전날 제출 현황 중간 점검 |
| 09:09 | `check_slack.py` | 전날 최종 제출·면제 확인 및 벌금 안내 |
| 09:10 | `send_slack.py` | 당일 인증 스레드 개설 |

## 2기 규칙

- 인증 이미지가 첨부된 스레드 댓글만 제출로 인정합니다.
- 미제출 벌금은 누적이나 가중 없이 1인당 항상 1,000원입니다.
- 벌금 계좌로 즉시 송금하지 않습니다. 미제출 횟수를 기록하고 추후 회식·모임 비용을 나눌 때 정산합니다.
- 다음날 09:09 최종 안내에 등록된 9명 전원의 누적 미제출 횟수·금액과 전체 누적 벌금액을 표시합니다. 금액은 날짜별 미제출 횟수에 1,000원을 곱해 계산합니다. 검사 대상은 각 멤버의 가입일부터 적용합니다.
- 면제권 사용 횟수에는 제한이 없습니다.
- 면제권은 `면제권 사용(사유: ...)` 형식으로 신청합니다.
- 면제 사유 판정 기준은 1기와 동일합니다. 질병·시험·공적 일정 계열은 승인하고, 개인 여가성 사유는 반려합니다.
- 2026년 10~12월 평일 공휴일(10월 5일·9일, 12월 25일)은 전원 면제일입니다. 토·일요일은 정기 검사 대상이 아니므로 면제일 목록에 넣지 않습니다.
- 아직 Slack ID가 없는 인원은 자동 검사 대상에서 제외됩니다.

현재 검사 대상 9명의 Slack ID는 `config.py`에서 관리합니다. 김수현·홍상우 님은 2026년 10월 2일 분량부터 자동 검사 대상에 포함됩니다.

## 설정

새 Slack 워크스페이스에 앱을 설치하고 대상 채널에 봇을 참여시킵니다.

- Bot Token Scope: `chat:write`
- Bot Token Scope: `channels:history` — 공개 채널인 경우
- Bot Token Scope: `groups:history` — 비공개 채널인 경우

게시와 채널·스레드 조회 모두 Bot Token으로 처리합니다.

GitHub Actions Secret에는 새 워크스페이스에서 발급된 토큰 하나를 등록합니다.

| Secret | 용도 |
|---|---|
| `SLACK_BOT_TOKEN` | 새 워크스페이스의 Bot User OAuth Token (`xoxb-...`) |

채널 ID는 비밀값이 아니므로 `config.py`의 `SLACK_CHANNEL_ID`에 저장합니다.

미제출 이력은 `miss_counts.v2.json`의 날짜별 Slack ID 목록으로 기록합니다. 누적 횟수는 이 목록에서 계산하므로 같은 날짜 검사를 다시 실행해도 중복 증가하지 않습니다. `check-slack.yml`은 자동 발급되는 `GITHUB_TOKEN`으로 파일을 갱신하며 `contents: write` 권한을 사용합니다. 별도 GitHub Secret 등록은 필요하지 않습니다.

## 로컬 실행

```bash
pip install requests

SLACK_BOT_TOKEN=xoxb-... python send_slack.py
SLACK_BOT_TOKEN=xoxb-... python midnight_report.py
SLACK_BOT_TOKEN=xoxb-... GITHUB_TOKEN=... GITHUB_REPOSITORY=yang5864/Slack-msg python check_slack.py
```

테스트:

```bash
python -m unittest discover -s tests -v
```

## 파일 구조

- `config.py`: 채널, 운영 기간, 멤버, 벌금과 면제 규칙
- `slack_utils.py`: Slack API 공통 호출과 오류 처리
- `send_slack.py`: 아침 인증글
- `midnight_report.py`: 자정 중간 점검
- `check_slack.py`: 다음날 최종 검사
- `miss_tracker.py`: 날짜별 미제출 이력 저장과 누적 횟수 계산
- `miss_counts.v2.json`: 2기 미제출 이력
- `state.v1.json`: 1기 종료 시점 상태의 읽기 전용 보관본

2기에는 누적 벌금 증액과 면제권 횟수 제한이 없습니다. 미제출 횟수만 기록하며 Gemini 기반 알고리즘 마스터 선정은 하지 않습니다.
