# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

Slack 알고리즘 스터디 자동화 봇. 세 가지 역할:

1. **아침 알림** (`send_slack.py`) — 매일 아침 "오늘의 인증!" 메시지를 채널에 전송
2. **미제출자 검사** (`check_slack.py`) — 다음날 아침 전날 스레드를 보고 미제출자에게 벌금 알림 + Gemini로 알고리즘 마스터 선정
3. **자정 중간 점검** (`midnight_report.py`) — 자정에 당일 제출 현황 브리핑

## 실행 방법

의존성 설치:
```bash
pip install requests pytz google-generativeai pillow
```

로컬 테스트 (환경변수 필요):
```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... python send_slack.py
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... GEMINI_API_KEY=... python check_slack.py
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... python midnight_report.py
```

## 아키텍처

### 실행 주체: cron-job.org
모든 워크플로우는 GitHub Actions 자체 스케줄러 없이 **cron-job.org가 `workflow_dispatch`를 외부에서 호출**하는 방식으로 동작. `.yml` 파일에 `schedule` 크론을 추가하면 이중 실행 발생.

### 실행 시각 (cron-job.org 기준 KST)
| 스크립트 | 실행 시각 | 비고 |
|---|---|---|
| `send_slack.py` | 매일 09:10 | check_slack Gemini 분석 완료 후 여유 확보 |
| `midnight_report.py` | 매일 00:00 | |
| `check_slack.py` | 매일 08:59 | 08:59 = 마감 시각, 실행 즉시 마감 |

### Slack 인증 글 탐색 방식
- `conversations.history`로 채널 메시지를 가져와 `"오늘의 인증!"` + 날짜 문자열(`MM월 DD일`)로 부모 메시지를 찾음
- `oldest` 파라미터로 당일 오전 9시 이후만 탐색 (limit 초과 방지)
- 찾은 메시지의 `ts`로 `conversations.replies`를 호출해 제출자 수집

### 날짜 처리 주의사항
- `check_slack.py`: **다음날 아침**에 실행 → `now - timedelta(days=1)`로 전날 날짜 사용
- `midnight_report.py`: **자정(00:00)에 실행** → 이미 날짜가 넘어간 상태이므로 동일하게 `now - timedelta(days=1)` 사용
- `send_slack.py`: **당일 아침**에 실행 → `now` 그대로 사용

### 전원 제출 처리 로직
- `midnight_report.py`: 자정 기준 전원 제출이면 "조기 종료" 메시지 발송. 미완료면 중간 점검 브리핑 발송.
- `check_slack.py` Step B-0: `conversations.history` 결과에서 `"조기 종료"` + `yesterday_str` 두 조건을 모두 만족하는 메시지가 있으면 `already_closed=True`. 날짜 조건 없이 키워드만 보면 이전 날 기록에 오탐 발생하므로 주의.
- `already_closed=True`이면 Step C에서 `missing_users=[]`로 강제 처리 → Step D의 전원 격려 메시지(얼리버드/막차 칭호)로 이어짐.
- 얼리버드/막차 탑승객은 `replies_with_ts`를 `ts` 기준 정렬해 추출. `replies_with_ts` 수집 시 `MEMBERS` 소속만 포함 (비멤버 댓글 오탐 방지).
- 시간 포맷은 `format_submit_time()` 담당. 자정(0시) → `오전 12시`, 정오(12시) → `오후 12시` (`dt.hour % 12 or 12` 처리).

### check_slack.py — check_and_notify() 실행 흐름

Step 0 → load_state() (폭탄 금액, 미제출 횟수)  
Step 0-1 → FULL_EXEMPT_DATES 체크 → 해당하면 폭탄 동결 메시지만 발송 후 즉시 return  
Step A → conversations.history로 `"오늘의 인증!" + yesterday_str` 부모 메시지 찾기  
Step B-0 → `"조기 종료" + yesterday_str` 동시 포함 메시지 있으면 `already_closed=True`  
Step B → conversations.replies로 스레드 수집 (`submitted_users`, `replies_with_ts`, `user_images`)  
Step C → `already_closed=True`면 `missing_users=[]` 강제, 아니면 MEMBERS 기준 미제출자 색출  
Step D-0 → Gemini 알고리즘 마스터 선정 (이미지 첨부 제출자만)  
Step D → 결과 메시지 전송 (전원 제출: 얼리버드/막차/폭탄 증가 / 미제출: 폭탄 청구/초기화)  

### check_slack.py — Gemini 알고리즘 마스터 선정 흐름

Step B에서 각 reply의 `files` 배열을 순회해 `image/*` mimetype인 첫 번째 파일 URL을 `user_images` dict에 저장. URL은 `url_private_download`를 우선하고 없으면 `url_private` 사용. 이미지 다운로드는 `img_headers`(Content-Type 없는 인증 전용 헤더) 사용 — 공통 `headers`에 `Content-Type: application/x-www-form-urlencoded`가 있어 바이너리 다운로드 시 오류 발생.

사용 모델: `gemini-3.1-flash-lite-preview` (`genai.GenerativeModel`로 초기화, RPM 15 제한)

Step D-0 순서:
1. `run_gemini_batch()` — RPM 15 제한 대응, `batch_size=10`으로 병렬 처리 후 배치 간 61초 대기
2. `analyze_problem()` — Gemini로 플랫폼·문제명·티어·환산점수·한줄평 추출 (JSON). `converted_score`는 즉시 `int()` 강제 변환 + `ValueError` 방어 처리.
3. 백준 문제는 `extract_boj_number()`로 번호 추출 후 **Solved.ac API**(`/api/v3/problem/show`)로 티어 확인 → `_SCORE_RANGES`의 티어 범위로 Gemini 점수 클램프. 프로그래머스는 `_PROGRAMMERS_CLAMP`로 레벨별 클램프. 두 플랫폼 모두 "티어/레벨 = 범위 보장, 범위 내 세부 점수 = Gemini 위임" 방식으로 통일.
4. 동점자 처리 — `resolve_tie()`: 전원 백준이면 `averageTries` 내림차순(높을수록 어려움), 그 외 `compare_with_gemini()` 토너먼트.
5. 공동 1등 탈락자는 슬랙 메시지에 별도 언급.

#### 난이도 통합 환산 기준 (티어 범위)
Gemini 점수를 아래 범위로 클램프. 범위 내 세부 점수는 Gemini가 체감 난이도로 결정.
```
백준 (Solved.ac 티어 기준):        프로그래머스 (레벨 기준):
브론즈 전 구간:  1~22점            Lv.0: 1~10점
실버   전 구간: 23~55점            Lv.1: 11~38점
골드   전 구간: 56~85점            Lv.2: 39~55점
플래티넘 전 구간: 86~100점         Lv.3: 56~85점
다이아·루비: 97~100점 (제외 대상)  Lv.4: 86~100점
```
`_SCORE_RANGES = [(1,22),(23,55),(56,85),(86,100),(97,100),(100,100)]` (tier_idx 순)
`_PROGRAMMERS_CLAMP = {0:(1,10), 1:(11,38), 2:(39,55), 3:(56,85), 4:(86,100)}`

#### 정규식 주의사항
`extract_boj_number()`에서 `\b` 대신 `(?<!\d)(\d{4,5})(?!\d)` 사용. Python 3 유니코드 모드에서 한글이 `\w`로 분류되어 `"2178번"`에서 `\b` 매칭 실패함.

### 벌금 룰

#### 폭탄 돌리기
- `state.json`의 `bomb_amount`는 **누적 원금** (0에서 시작/리셋)
- **기본 실효 벌금** = `effective_bomb = max(1000, bomb_amount)` — 최소 1,000원 보장
- 전원 제출 + 평일: `bomb_amount += 1000` (상한 10,000원). 단 첫 전원 제출일은 effective_bomb이 1,000원으로 유지됨 (0→1000이지만 max(1000,1000)=1000)
- 전원 제출 + 주말: 변화 없음
- 미제출자 발생: `max(effective_bomb, 미제출자 수 * 1000)` 전액을 미제출자 합산 납부 → `bomb_amount = 0`으로 리셋
- 분담 방식(n빵 or 몰아주기)은 미제출자 자율

#### 상습범 가중처벌
- 폭탄과 별개로 개인 추가 납부
- n번째 미제출 시 `(n-1) * 1000`원 (1번째=0원, 2번째=1,000원, ...)
- `calc_fines(missing_uids, miss_counts)` 함수가 계산. 반환값: `{uid: penalty}`, `{name: new_count}`

#### 면제 처리
- `FULL_EXEMPT_DATES` (dict): 전원 면제 날짜 → 폭탄 동결, 미제출 체크 없음, 안내 메시지만 발송
- 추가 방법: `"MM월 DD일": "사유"` 형식으로 한 줄 추가

```python
FULL_EXEMPT_DATES = {
    "04월 13일": "스켈레톤 프로젝트 마감일",
}
```

### 상태 영속화 (state.json)
- `bomb_amount` (int, 0~10000): 폭탄 누적 원금. 실제 터질 때 총 벌금은 코드에서 `max(max(1000, bomb_amount), 미제출자 수 * 1000)`로 계산
- `miss_counts` (dict): 멤버 이름 → 누적 미제출 횟수 (예: `"강채연": 2`)
- `check_slack.py` 실행 시 **GitHub API**(`/repos/{owner}/{repo}/contents/state.json`)로 읽고(GET) 씀(PUT)
- `GITHUB_TOKEN`은 Actions 자동 발급 토큰 (`secrets.GITHUB_TOKEN`). 별도 등록 불필요.
- `check-slack.yml`에 `permissions: contents: write` 설정 필수
- `load_state()` 실패 시 기본값(`bomb_amount=BOMB_STEP(=1000), miss_counts 전원 0`)으로 폴백. `bomb_amount` 기본값은 0이 아닌 1000 주의.

### GitHub Secrets
| Secret | 용도 |
|---|---|
| `SLACK_BOT_TOKEN` | Tetz봇 Bot User OAuth Token (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 대상 채널 ID |
| `GEMINI_API_KEY` | Gemini API 키 (`check_slack.py`만 사용) |

`SLACK_WEBHOOK_URL`은 더 이상 사용하지 않음 (Tetz봇으로 통일).

### 멤버 명단
세 스크립트 모두 `MEMBERS` dict를 각자 보유 (19명). 멤버 변경 시 세 파일 모두 수정 필요. `state.json`의 `miss_counts`는 이름 키라 멤버 이름 변경 시 `state.json`도 함께 수정 필요.
