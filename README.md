# 🤖 Tetz Bot — LLM-as-a-Judge 기반 스터디 자동화 파이프라인

매일 19명의 알고리즘 풀이 인증을 자동으로 관리하고, **Gemini 멀티모달 AI**로 스크린샷을 분석해 오늘의 '알고리즘 마스터'를 선정하는 Slack 자동화 시스템입니다. 단순한 크론(Cron) 봇을 넘어, 실무 수준의 **LLM 평가 파이프라인**과 **장애 내성(Fault Tolerance)** 을 갖추는 데 집중했습니다.

---

## 🎯 프로젝트 기획 배경 및 성과

- **문제 인식**: 스터디 관리자의 반복적인 리소스(출석 확인, 벌금 고지, 각기 다른 플랫폼의 난이도 비교) 낭비 발생
- **해결 방안**: Slack API와 Multimodal LLM을 결합한 완전 자동화 파이프라인 구축
- **기대 효과**: 스터디원들의 승부욕을 자극하는 게이미피케이션(Gamification) 요소 도입으로 인증 참여율 100% 달성 및 관리 리소스 0%로 단축

| 봇 | 실행 시각 (KST) | 역할 |
|---|---|---|
| `send_slack.py` | 매일 09:10 | "오늘의 인증!" 스레드 개설 |
| `midnight_report.py` | 매일 00:00 | 자정 현황 브리핑 / 조기 종료 선언 |
| `check_slack.py` | 매일 08:59 | 미제출자 벌금 고지 + 알고리즘 마스터 선정 |

---

## ✨ Key Technical Highlights

### 1. ⚖️ LLM-as-a-Judge 패턴의 프로덕션 도입

요즘 LLM 업계에서 가장 주목받는 **'LLM-as-a-Judge(심판으로서의 LLM)'** 패턴을 성공적으로 구현했습니다. 백준·프로그래머스 등 플랫폼마다 상이한 난이도 체계를 수백 줄의 조건문으로 하드코딩하는 대신, 정교한 **프롬프트 엔지니어링 하나로 복잡한 평가 기준을 퉁치고** 결과를 깔끔한 JSON으로 뽑아내는 현업 시니어 수준의 아키텍처 설계 스킬을 구사했습니다.

**① Multimodal Judge — 이미지 기반 난이도 평가**

```
유저 스크린샷 이미지
        ↓
  Gemini Vision API
        ↓
  플랫폼 식별 + 문제명 추출 + 난이도 환산점수 (1~100) + 한줄 평 → JSON
```

백준·프로그래머스 어느 플랫폼이든 동일한 100점 척도로 환산해 공정하게 비교합니다. 별도의 크롤러나 플랫폼별 파서 없이 프롬프트 하나로 처리합니다.

**② Comparative Judge — 동점자 토너먼트 비교**

점수가 동일한 공동 1등 발생 시, Gemini에게 두 문제를 직접 비교시켜 최종 마스터를 결정합니다.

```
"다음 두 문제 중 어느 것이 더 어렵습니까?
 문제 1: 스타트링크 (5014번) (백준, 실버 1)
 문제 2: 구명보트 (프로그래머스, Lv.2)
 반드시 '1' 또는 '2'만 출력하세요."
```

N명의 동점자를 토너먼트 방식으로 순차 비교해 최종 1인을 선별합니다.

---

### 2. 🛡️ RAG 아키텍처를 응용한 환각(Hallucination) 제어

LLM의 고질적 한계인 **환각 현상을 시스템 레벨의 교차 검증(Cross-Validation)** 으로 방어했습니다. LLM은 이미지를 읽어내는 **OCR 및 기초 평가 도구로만 활용**하고, 백준 문제의 경우 추출된 식별 번호로 **Solved.ac API를 호출해 절대 팩트 데이터를 가져와 LLM 추측값을 덮어씌웁니다.**

```
Gemini 분석 결과 (추측값)
  platform:       "백준"
  problem_name:   "미로 탐색 (2178번)"  ← 번호 추출
  original_tier:  "실버 I"              ← LLM 추측
  converted_score: 35                   ← LLM 추측
          ↓
  Solved.ac API 호출: level = 10
          ↓
  original_tier:  "실버 1"   ← 실측값으로 덮어씀
  converted_score: 40        ← 공식 계산값으로 교체
  average_tries:   3.2       ← 동점 타이브레이커용 추가
```

**프롬프트 레벨 방어도 병행**합니다. LLM이 배경지식으로 티어를 추측하지 않도록 환각 금지 규칙을 명시합니다.

```
🚨 [절대 규칙: 환각(Hallucination) 금지!] 🚨
1. 문제의 티어를 배경지식으로 절대 추측하지 마.
2. 반드시 화면에 텍스트로 적혀 있는 티어나 아이콘 색상을 그대로 읽어.
3. 팩트 기반으로 확인된 티어만 'original_tier'에 적어.
```

---

### 3. 🚦 비동기 병렬 처리 및 Rate Limit 우회 로직

19명의 이미지를 순차 처리할 때 발생하는 지연 시간과 Gemini 무료 API의 RPM(분당 요청 수) 한도를 해결하기 위해 **배치(Batch) 기반 병렬 처리**를 도입했습니다.

```python
# 10명 단위로 ThreadPoolExecutor 병렬 분석
with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
    batch_results = list(executor.map(analyze_problem, batch))

# 슬라이딩 윈도우 초기화 → 429(Too Many Requests) 원천 차단
if i + batch_size < len(tasks):
    time.sleep(61)
```

- `batch_size=10`, RPM=15 모델 기준 안전 마진 확보 (10 < 15)
- 배치 완료 후 61초 대기로 RPM 슬라이딩 윈도우 완전 초기화

---

### 4. 🦺 방어적 프로그래밍 (Defensive Programming)

LLM이 프롬프트 지시를 무시하고 예상 외 텍스트(예: `"75점"`, `"난이도 측정 불가"`)를 반환할 때 발생하는 `JSONDecodeError` 및 `ValueError`를 방어합니다. 에러 발생 시 프로세스가 죽지 않고 해당 유저를 0점 처리한 뒤 다음 스레드를 정상적으로 이어가는 **Fallback 로직**을 구현했습니다.

```python
try:
    result['converted_score'] = int(
        str(result.get('converted_score', 0)).replace('점', '').strip()
    )
except ValueError:
    result['converted_score'] = 0  # 파이프라인 중단 없이 계속 진행
```

---

### 5. 🏆 동점 처리 알고리즘

| 상황 | 타이브레이커 | 선택 근거 |
|---|---|---|
| 백준 vs 백준 | `averageTries` 내림차순 | 평균 시도 횟수가 높을수록 체감 난이도 높음. `acceptedUserCount`는 오래된 유명 문제에 편향 |
| 그 외 혼합 | Gemini 비교 판정 | 프로그래머스 공개 API 없음, LLM 직접 비교가 유일한 크로스플랫폼 수단 |

공동 1등 탈락자도 Slack 메시지에 별도 언급합니다.

---

## 🛠️ Trouble Shooting

<details>
<summary><b>1. 한국어 특성을 고려하지 못한 정규식(Regex) 매칭 버그 해결</b></summary>

**문제 상황**: 백준 문제 번호를 추출하기 위해 `\b(\d{4,5})\b` (단어 경계) 정규식을 사용했으나, LLM이 `"2178번"`이라고 출력할 경우 Python 유니코드 환경에서 한글(`번`)을 `\w` 문자로 인식하여 `\b` 경계 매칭에 실패하고 Solved.ac API를 타지 못하는 버그 발생.

**해결 방법**: 정규식의 **전방/후방 탐색(Negative Lookahead/Lookbehind)** 을 활용하여 `(?<!\d)(\d{4,5})(?!\d)`로 로직 개선. 한글 띄어쓰기 유무와 무관하게 순수 4~5자리 숫자만 완벽하게 추출하도록 안정성 확보.

```python
# Before: 한글 앞 \b 매칭 실패
re.search(r'\b(\d{4,5})\b', '2178번')   # → None

# After: 숫자 앞뒤에 다른 숫자가 없는 조건으로 대체
re.search(r'(?<!\d)(\d{4,5})(?!\d)', '2178번')  # → '2178'
```

</details>

<details>
<summary><b>2. LLM 모델 일일 한도(RPD) 초과로 인한 파이프라인 중단 대응</b></summary>

**문제 상황**: 초기 Gemini 2.5 Flash 모델 적용 시, 배치 병렬 처리로 RPM(분당 요청)은 회피했으나, 일일 한도(RPD) 제약으로 인해 스터디원 전체 처리 중 404/429 에러 발생.

**해결 방법**: API Limit 문서를 분석한 후, 추론 속도가 빠르고 RPD 한도가 500회로 넉넉한 **Gemini 3.1 Flash Lite Preview** 모델로 마이그레이션 수행. 병렬 처리 로직과 결합하여 비용 발생 없이 완전한 자동화 유지 성공.

</details>

---

## ⚙️ System Architecture

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
    │       ├─ Gemini API: 이미지 배치 분석 (Multimodal Judge)
    │       ├─ Solved.ac API: 백준 문제 난이도 교차 검증 (RAG 패턴)
    │       ├─ resolve_tie(): BOJ averageTries / Gemini 토너먼트 비교 판정
    │       └─ Slack API: 결과 발송 (벌금 고지 / 마스터 선정 + 공동 1등 위로)
    │
    └─ [09:10] send_slack.py
            └─ Slack API: 오늘의 인증 스레드 개설
```

> `schedule` 크론 대신 외부 트리거(cron-job.org → `workflow_dispatch`) 방식을 채택해 GitHub Actions 서버 지연으로 인한 이중 실행 문제를 원천 차단했습니다.

---

## 💻 Tech Stack

| 분류 | 사용 기술 |
|---|---|
| **AI / LLM** | Google Gemini API (`gemini-3.1-flash-lite-preview`), Prompt Engineering |
| **API Integration** | Slack Web API, Solved.ac API v3 |
| **Language & Libs** | Python 3.9+, `google-generativeai`, `concurrent.futures`, `Pillow`, `re`, `json` |
| **CI/CD & Infra** | GitHub Actions, cron-job.org |

---

## 🚀 Setup & Installation

**1. 의존성 패키지 설치**
```bash
pip install requests pytz google-generativeai pillow
```

**2. 환경 변수 (GitHub Secrets) 등록**

| Secret Key | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Tetz봇 OAuth Token (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 알림을 전송할 Slack 채널 ID |
| `GEMINI_API_KEY` | Google AI Studio에서 발급받은 API 키 |

**3. 로컬 환경 테스트**
```bash
SLACK_BOT_TOKEN="xoxb-..." SLACK_CHANNEL_ID="C..." GEMINI_API_KEY="..." python check_slack.py
```
