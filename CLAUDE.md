# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

Slack 알고리즘 스터디 자동화 봇. 세 가지 역할:

1. **아침 알림** (`send_slack.py`) — 매일 아침 "오늘의 인증!" 메시지를 채널에 전송
2. **미제출자 검사** (`check_slack.py`) — 다음날 아침 전날 스레드를 보고 미제출자에게 벌금 알림
3. **자정 중간 점검** (`midnight_report.py`) — 자정에 당일 제출 현황 브리핑

## 실행 방법

의존성 설치:
```bash
pip install requests pytz
```

로컬 테스트 (환경변수 필요):
```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... python send_slack.py
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... python check_slack.py
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... python midnight_report.py
```

## 아키텍처

### 실행 주체: cron-job.org
모든 워크플로우는 GitHub Actions 자체 스케줄러 없이 **cron-job.org가 `workflow_dispatch`를 외부에서 호출**하는 방식으로 동작. `.yml` 파일에 `schedule` 크론을 추가하면 이중 실행 발생.

### Slack 인증 글 탐색 방식
- `conversations.history`로 채널 메시지를 가져와 `"오늘의 인증!"` + 날짜 문자열(`MM월 DD일`)로 부모 메시지를 찾음
- `oldest` 파라미터로 당일 오전 9시 이후만 탐색 (limit 초과 방지)
- 찾은 메시지의 `ts`로 `conversations.replies`를 호출해 제출자 수집

### 날짜 처리 주의사항
- `check_slack.py`: **다음날 아침**에 실행 → `now - timedelta(days=1)`로 전날 날짜 사용
- `midnight_report.py`: **자정(00:00)에 실행** → 이미 날짜가 넘어간 상태이므로 동일하게 `now - timedelta(days=1)` 사용
- `send_slack.py`: **당일 아침**에 실행 → `now` 그대로 사용

### 실행 시각 (cron-job.org 기준 KST)
| 스크립트 | 실행 시각 |
|---|---|
| `send_slack.py` | 매일 09:00 |
| `midnight_report.py` | 매일 00:00 |
| `check_slack.py` | 매일 08:59 (08:59 = 마감 시각, 실행 즉시 마감) |

### 전원 제출 처리 로직
- `midnight_report.py`: 자정 기준 전원 제출이면 "조기 종료" 메시지 발송. 미완료면 중간 점검 브리핑 발송.
- `check_slack.py` Step B-0: `conversations.history` 결과에서 `"조기 종료"` + `yesterday_str` 두 조건을 모두 만족하는 메시지가 있으면 `already_closed=True`. 날짜 조건 없이 키워드만 보면 이전 날 기록에 오탐 발생하므로 주의.
- `already_closed=True`이면 Step C에서 `missing_users=[]`로 강제 처리 → Step D의 전원 격려 메시지(얼리버드/막차 칭호)로 이어짐. `return`으로 조기 종료하면 아침 브리핑이 생략되는 모순 발생.
- 얼리버드/막차 탑승객은 `replies_with_ts`를 `ts` 기준 정렬해 추출. `replies_with_ts` 수집 시 `MEMBERS` 소속만 포함 (비멤버 댓글 오탐 방지).
- 시간 포맷은 `format_submit_time()` 담당. 자정(0시) → `오전 12시`, 정오(12시) → `오후 12시` (`dt.hour % 12 or 12` 처리).

### GitHub Secrets
| Secret | 용도 |
|---|---|
| `SLACK_BOT_TOKEN` | Tetz봇 Bot User OAuth Token (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 대상 채널 ID |

`SLACK_WEBHOOK_URL`은 더 이상 사용하지 않음 (Tetz봇으로 통일).

### 멤버 명단
세 스크립트 모두 `MEMBERS` dict를 각자 보유 (19명). 멤버 변경 시 세 파일 모두 수정 필요.
