# Tetz Bot — Slack 알고리즘 스터디 자동화 봇

> 매일 19명의 알고리즘 풀이 인증을 자동으로 관리하고, **Gemini 멀티모달 AI**로 스크린샷을 분석해 오늘의 알고리즘 마스터를 선정하는 Slack 자동화 봇

---

## Overview

알고리즘 스터디의 반복적인 관리 업무(출석 확인, 벌금 고지, 난이도 비교)를 전부 자동화한 프로젝트입니다. 단순한 알림 봇을 넘어, **이미지 기반 LLM 평가 파이프라인**을 설계하고 프로덕션 수준의 안정성을 갖추는 데 집중했습니다.

| 봇 | 실행 시각 (KST) | 역할 |
|---|---|---|
| `send_slack.py` | 매일 09:10 | "오늘의 인증!" 스레드 개설 |
| `midnight_report.py` | 매일 00:00 | 자정 현황 브리핑 / 조기 종료 선언 |
| `check_slack.py` | 매일 08:59 | 미제출자 벌금 고지 + 알고리즘 마스터 선정 |

---

## Key Technical Highlights

### 1. LLM-as-a-Judge 패턴 구현

**LLM-as-a-Judge**는 LLM을 단순 생성기가 아닌 *평가자(Judge)* 로 활용하는 패턴으로, 복잡한 규칙 기반 로직을 자연어 프롬프트 하나로 대체합니다. 현업 AI 엔지니어링에서 평가 파이프라인, A/B 테스트 자동화 등에 널리 쓰이는 기법입니다.

이 프로젝트에서는 두 단계로 적용됩니다:

**① 난이도 평가 (Multimodal Judge)**
```
스크린샷 이미지 → Gemini Vision
     ↓
플랫폼 식별 + 문제 추출 + 난이도 환산점수 (1~100) + 한줄 평 → JSON
```
백준·프로그래머스 등 플랫폼이 달라도 동일한 100점 척도로 환산해 공정하게 비교합니다. 별도의 크롤러나 플랫폼별 파서 없이 프롬프트 하나로 처리합니다.

**② 동점자 비교 (Comparative Judge)**

점수가 동일한 공동 1등이 나오면 Gemini에게 두 문제를 직접 비교시킵니다:
```
"다음 두 문제 중 어느 것이 더 어렵습니까?
 문제 1: 스타트링크 (5014번) (백준, 실버 1)
 문제 2: 구명보트 (프로그래머스, Lv.2)
 반드시 '1' 또는 '2'만 출력하세요."
```
토너먼트 방식으로 N명의 동점자를 순차 비교해 최종 마스터를 결정합니다.

---

### 2. Hallucination 방어 전략 (Hybrid Validation)

LLM의 환각(Hallucination)을 프롬프트 레벨과 시스템 레벨 두 층으로 방어합니다.

**프롬프트 레벨 — 사실 기반 읽기 강제**
```
🚨 [절대 규칙: 환각(Hallucination) 금지!] 🚨
1. 문제의 티어를 배경지식으로 절대 추측하지 마.
2. 반드시 화면에 텍스트로 적혀 있는 티어나 아이콘 색상을 그대로 읽어.
3. 팩트 기반으로 확인된 티어만 'original_tier'에 적어.
```

**시스템 레벨 — 외부 API 교차 검증**

백준 문제는 Gemini가 추출한 문제 번호로 **Solved.ac API**를 호출해 실제 티어와 점수를 덮어씁니다. LLM 추측값을 신뢰하지 않고 공식 데이터로 대체하는 RAG(Retrieval-Augmented Generation)적 접근입니다.

```
Gemini 분석 결과
  platform: "백준"
  problem_name: "미로 탐색 (2178번)"   ← 번호 추출
       ↓
Solved.ac API: level=10 (실버 1)
       ↓
original_tier = "실버 1"  ← 덮어씀
converted_score = 40       ← 공식 계산값으로 교체
average_tries = 3.2        ← 동점 타이브레이커용
```

---

### 3. 동점 처리 알고리즘

| 상황 | 타이브레이커 | 근거 |
|---|---|---|
| 백준 vs 백준 | `averageTries` 내림차순 | 평균 시도 횟수가 높을수록 체감 난이도 높음. `acceptedUserCount`는 오래된 유명 문제에 편향됨 |
| 그 외 혼합 | Gemini 비교 판정 | 프로그래머스 공개 API 없음, LLM 직접 비교가 유일한 크로스플랫폼 수단 |

공동 1등 탈락자도 Slack 메시지에 별도 언급합니다.

---

### 4. Rate Limit 대응 배치 처리

Gemini 무료 티어 RPM(분당 요청 수) 제한 내에서 19명을 처리하기 위해 **배치 병렬 처리** 전략을 사용합니다.

```python
# ThreadPoolExecutor로 배치 내 병렬 처리
# 배치 완료 후 61초 대기로 RPM 윈도우 리셋
with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
    batch_results = list(executor.map(analyze_problem, batch))
```

- `batch_size=10`, RPM=15인 모델 기준 안전 마진 확보 (10 < 15)
- 배치 간 61초 대기 → RPM 슬라이딩 윈도우 완전 초기화

---

### 5. LLM 출력 안전 파싱

LLM은 지시를 따르지 않거나 예상 외 형식을 반환할 수 있습니다. 숫자 필드에 `"75점"` 같은 문자열이 오는 경우를 방어합니다.

```python
try:
    result['converted_score'] = int(
        str(result.get('converted_score', 0)).replace('점', '').strip()
    )
except ValueError:
    result['converted_score'] = 0  # 파이프라인 중단 없이 계속 진행
```

---

## System Architecture

```
cron-job.org
    │  HTTP POST (workflow_dispatch)
    ▼
GitHub Actions
    ├─ [00:00] midnight_report.py
    │       └─ Slack API: 자정 현황 브리핑 / 조기 종료 선언
    │
    ├─ [08:59] check_slack.py
    │       ├─ Slack API: 스레드 탐색 → 제출자/이미지 수집
    │       ├─ Gemini API: 이미지 배치 분석 (멀티모달 Judge)
    │       ├─ Solved.ac API: 백준 문제 난이도 교차 검증
    │       ├─ resolve_tie(): BOJ averageTries / Gemini 비교 판정
    │       └─ Slack API: 결과 발송 (벌금 고지 or 전원 칭찬 + 마스터 선정)
    │
    └─ [09:10] send_slack.py
            └─ Slack API: 오늘의 인증 스레드 개설
```

> `schedule` 크론 대신 외부 트리거(cron-job.org → `workflow_dispatch`) 방식을 채택해 GitHub Actions 이중 실행 문제를 원천 차단했습니다.

---

## Tech Stack

| 분류 | 기술 |
|---|---|
| **AI / LLM** | Google Gemini API (멀티모달, gemini-3.1-flash-lite-preview) |
| **외부 API** | Slack Bot API, Solved.ac API v3 |
| **런타임** | Python 3.9+, `google-generativeai`, `Pillow`, `requests` |
| **인프라** | GitHub Actions, cron-job.org |

---

## Setup

**1. 의존성 설치**
```bash
pip install requests pytz google-generativeai pillow
```

**2. GitHub Secrets 등록**

| Secret | 설명 |
|---|---|
| `SLACK_BOT_TOKEN` | Tetz봇 Bot User OAuth Token (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 대상 채널 ID |
| `GEMINI_API_KEY` | Google AI Studio API 키 |

**3. cron-job.org 등록**

각 워크플로우의 `workflow_dispatch` 엔드포인트를 아래 시각에 트리거하도록 설정합니다.

| URL | 실행 시각 (KST) |
|---|---|
| `.../workflows/midnight-report.yml/dispatches` | 매일 00:00 |
| `.../workflows/check-slack.yml/dispatches` | 매일 08:59 |
| `.../workflows/slack-notify.yml/dispatches` | 매일 09:10 |

**4. 로컬 테스트**
```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C... GEMINI_API_KEY=... python check_slack.py
```
