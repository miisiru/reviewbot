# reviewbot

[English](README.md) | **한국어**

[theherta.com](https://theherta.com) 기록 검토(모더레이션)를 돕는 도구입니다. 제출된 붕괴: 스타레일 클리어 영상을 받아서
편성 · 성혼 · 광추 중첩 · 전투 결과 · 보유 효과(계정 공통 효과) 발동을 영상에서 읽고, 제출 내용과 맞춰
**APPROVE / CHECK / REJECT** 와 신뢰도(%)를 냅니다. 판정에는 AI(언어 모델)를 쓰지 않습니다.
영상 처리(OpenCV)와 OCR(PaddleOCR PP-OCRv5)만 씁니다.

사이트에서 승인 · 거절 버튼을 누르는 일은 사람이 합니다. 도구는 판정과 근거만 냅니다.
API 로 결정을 보내는 명령은 있지만 `--yes` 를 붙여야만 보냅니다.

---

## 0. 먼저 읽을 것

### 0-1. Chrome DevTools 없이 돌리는 방식

처음에는 AI 에이전트가 Chrome DevTools(브라우저 자동 조종)로 검토 페이지를 열어 대기열을 읽고 카드를 펼쳤습니다.
지금은 사이트 검토 API 를 직접 부르는 방식으로도 똑같이 돌 수 있습니다.

1. 브라우저에서 theherta.com 에 로그인합니다(Discord). 그 세션의 토큰을 **한 번만** 꺼내 `config.json` 에 넣습니다
   (아래 「2-5. 토큰 얻기」).
2. `python tools/mod_api.py queue` 로 대기열을 받습니다. 결과는 `work/queue.json` 에 저장됩니다.
3. `python tools/run_queue.py --limit 5` 로 다섯 건을 차례로 판정합니다(받기 → 메뉴 구간 찾기 → 판정).
   `--fetch` 를 붙이면 1~2 단계를 한 번에 합니다.
4. 결과는 `runs/<rev>/auto.json` 과 `work/results.jsonl` 에 남습니다. `--webhook question|review` 를 붙이면
   디스코드로도 보냅니다.

access token 은 한 시간쯤 지나면 만료됩니다. `config.json` 에 refresh token · Supabase 주소 · anon 키를 함께 넣어 두면
`mod_api.py` 가 알아서 새 토큰을 받아 `config.json` 에 다시 씁니다. 브라우저는 처음 토큰을 꺼낼 때만 필요합니다.

> 이 API 호출 방식(`mod_api.py`)은 사이트 화면이 쓰는 요청을 그대로 따라 만든 것이고, 실제 서버에 대해서는 아직
> 시험하지 않았습니다. 처음 쓸 때 `queue` 결과부터 확인하세요.

### 0-2. 사이트 운영자께: 이런 API 가 있으면 좋겠습니다

지금은 로그인 세션 토큰을 꺼내 쓰는 방식이라 불편하고 깨지기 쉽습니다. 아래가 있으면 자동 검토를 안전하고 깔끔하게
붙일 수 있습니다. 중요한 것부터 적었습니다.

1. **봇용 API 키.** 검토자 계정에 묶인 오래가는 키(만료 · 취소 가능, 권한은 대기열 읽기 · 검토 중 표시 · 의견 남기기로 제한).
   지금처럼 Supabase 세션 토큰을 브라우저에서 꺼내 쓰지 않아도 되게.
2. **결정 대신 「의견」을 남기는 자리.** 봇이 승인 · 거절을 직접 누르지 않고, 카드에 판정 · 신뢰도 · 근거(영상 시각 링크,
   프레임 이미지)를 붙여 두면 사람이 보고 누르는 방식. 예: `POST /api/mod/reviews/<id>/notes`
   `{"verdict":"reject","confidence":92,"reasons":[...],"evidence":[{"t":229,"image_url":...}]}`
3. **제출 자료에 게임 ID.** 캐릭터 · 광추를 영어 이름 대신 게임 ID(AvatarID, EquipmentID)로도. 지금은 이름을 13개 언어
   TextMap 에서 찾아 맞추는데, 문장부호가 다르게 적힌 이름(「Dance Dance Dance」 = 「Dance! Dance! Dance!」)에서 헷갈립니다.
4. **대기열 항목에 우선순위와 상태.** 후원자 줄인지, 몇 번째 재검토인지, 같은 영상 · 같은 UID 로 이미 등록된 기록이 있는지
   (지금은 「이미 사이트에 있는 영상」 거절을 사람이 찾아야 합니다). 예: `GET /api/mod/reviews/<id>/duplicates`
5. **새 제출 알림.** 대기열을 주기적으로 읽지 않도록 웹후크나 SSE 로 새 건을 알려 주기.
6. **봇용 「검토 중」 표시.** 지금은 1분짜리라 판정(1~2분)보다 짧습니다. 시간을 정해 잡을 수 있게(`{"ttl": 300}`) 하고
   표시 이름에 「bot」이 보이게.
7. **거절 사유 템플릿 API.** 사유를 자유 글 대신 템플릿 번호 + 값 + 언어로(`{"template":"superimp_mismatch","char":...,
   "submitted":5,"video":1,"lang":"zh"}`) 받아 사이트가 그 언어로 글을 만들도록.
8. **사용 한도 문서.** 초당 몇 번까지 불러도 되는지.

---

## 1. 지금 판정 방식 (채택한 것)

한 건은 이 순서로 처리합니다.

```
prep.py              영상 받기(H.264 720p, 빌리빌리 여러 파트는 모두, 깨지면 480p → 1080p 로 다시)
                     (받은 영상은 건끼리 나눠 쓴다: video_cache.py)
segment_pipeline.py  영상을 전투 · 쇼케이스로 나누고(scan_battle_boundaries.py · scan_showcases.py, 영상마다 캐시),
                     이 건의 전투(타임스탬프)와 쇼케이스를 고른다 → runs/<rev>/segment_selection.json
battle_sheets.py     고른 전투의 시트(처음 · 끝 쪽 한 장씩이 보고에 붙는다)
tabs.py              고른 쇼케이스 안에서 캐릭터 화면(왼쪽 메뉴)이 보이는 구간을 찾고, 광추 · 성혼 탭이 열린 프레임을 캐릭터마다 남김
auto_judge.py
  ├ judge.py  누구 화면인지 · 광추 이름 · 중첩 · 성혼(자물쇠 수)
  │           (그림 근거는 imgrec.py, 읽은 것이 애매하면 같은 화면을 더 촘촘히 다시 읽는다)
  ├ hud.py    전투가 끝나는 순간의 HUD 값(소모 라운드 / 남은 행동 수치 / 절망 ⧗N | x)
  ├ gp.py     보유 효과 발동 배너(카스토리스 「달의 고치의 비호」, 은랑 LV.999 「999 디펜더」)
  └ UID · 시작 시각 · 신뢰도 · 판정
```
`segment_selection.json` 이 없으면(옛 판, 또는 `tabs.py` 를 손으로 돌린 경우) `auto_judge.py` 는 예전처럼 영상 전체로 판정합니다.

### 1-1. 원칙
- **결과 화면은 근거로 쓰지 않습니다.** 결과 화면은 최고 기록을 보여 줄 수 있어 이번 런과 다를 수 있습니다.
  전투 중 HUD 의 「전투 종료」 순간 값만 씁니다.
- **OCR 은 위치를 아는 작은 칸만** 읽고, 읽은 글을 해석하지 않습니다. 제출된 후보 이름(13개 언어 TextMap)
  가운데 가장 가까운 것을 고릅니다. 글을 자유롭게 읽어 뜻을 짐작하는 방식은 오류가 많아 쓰지 않습니다.
- **언어 모델(OCR)은 영상마다 고릅니다.** 광추 화면 두 장을 중국어 · 한국어 · 라틴 · 러시아 · 태국어 모델로 읽어
  제출 이름과 가장 잘 맞는 모델을 씁니다.
- **못 읽은 것은 「없음」이 아닙니다.** 읽지 못한 항목은 신뢰도를 깎고 CHECK 로 보냅니다. 「미표시」 거절은 그 화면을
  정말 찾지 못했을 때만 합니다.

### 1-2. 캐릭터 화면 찾기 (tabs.py)
- 왼쪽 메뉴 아이콘 6개(디테일 · 광추 · 행적 · 유물 · 성혼 · 정보, 언어 무관)를 여러 크기로 찾아 메뉴 배치를 정합니다.
  화면비 고정 비율을 쓰지 않으므로 PC 16:9, 휴대폰 와이드, 태블릿 4:3, 좌우 검은 띠 영상에서 모두 됩니다.
  종말의 환영 「열람 모드」의 5줄 메뉴도 찾습니다.
- 켜진 탭은 아이콘의 옅은 금색 비율로 정합니다. 0.3초짜리 빠른 클릭도 잡습니다.
- 영상을 1초에 한 장씩 훑어 메뉴 구간을 찾고(최대 6개 프로세스로 나눠 동시에), 그 구간만 촘촘히 봅니다.
- 머리글(길 / 이름) 글자 모양이 바뀌면 다른 캐릭터로 봅니다. 성혼 탭을 연 채 캐릭터를 넘겨도 캐릭터마다 따로 잡습니다.
  제작자 워터마크는 늘 켜져 있는 글자로 찾아서 비교에서 뺍니다.

### 1-3. 누구 화면인지 (judge.py)
순서대로 시도하고, 처음 확실하게 맞는 것을 씁니다.
1. 머리글 이름 OCR 이 제출 캐릭터 이름과 맞음(0.7 이상, 또는 0.6 이상이고 다음 후보와 0.3 차)
2. 성혼 화면이면 **성혼 이름 6줄**(캐릭터마다 다름, 13개 언어. `tools/eidolon_names.json`)이 한 캐릭터와 맞음
   (2줄 이상, 둘째 후보는 첫째의 1/3 이하). 머리글이 워터마크에 덮여도 됩니다.
3. 광추 제목이 한 캐릭터의 제출 광추와만 뚜렷이 맞음(0.9 이상, 다음과 0.25 차)
4. 바로 앞 디테일 화면의 큰 이름(구간 끝 프레임). 어떤 이름과도 안 맞는 이름 줄은 플레이어 이름, 곧 개척자입니다.
   매 화면에 찍히는 버튼 글(「캐릭터 공략」 등)은 이름으로 치지 않습니다.
5. 남은 캐릭터가 하나뿐이면 그 캐릭터

근거 두 가지가 같은 캐릭터를 가리키면 확실한 것으로 보고 신뢰도를 깎지 않습니다.

### 1-4. 광추 · 중첩
- 광추 패널 제목을 제출 광추의 모든 언어 이름과 비교합니다. 0.7 미만이면 「광추 다름」, 0.7~0.9 는 감점만 합니다.
  길 이름 줄(「记忆」)은 제목 점수에서 뺍니다(그 낱말이 든 광추 이름과 부분 일치하므로).
- 중첩은 「중첩 N단계 / Superimposition N / 叠影N阶 / 重畳ランクN …」 줄의 숫자입니다(12개 언어 표기와 비슷한 줄).

### 1-5. 성혼
- 성혼 노드 6개를 원 찾기로 찾고, 노드 배치 기준(16:9, 왼쪽 캐릭터 줄 배치, 4:3 태블릿) 중 맞는 것에 끼워 맞춥니다.
- 노드마다 자물쇠 그림 틀과 비교한 점수의 구간 최댓값을 씁니다. 0.6 이상이면 잠김, 0.5~0.65 는 「애매」(감점)입니다.
- 성혼 구간은 영상 원래 프레임(최대 30fps)으로 읽습니다. 성혼 탭을 0.3초만 여는 영상이 있기 때문입니다.
- 메뉴에서 **켜진 탭이 성혼인 프레임만** 씁니다. 행적 화면의 노드 둘레가 성혼 배치에 들어맞는 일이 있어서입니다.
- 캐릭터 이름이 바뀐 뒤 0.1초는 쓰지 않습니다. 머리글이 먼저 바뀌고 노드 그림은 늦게 바뀝니다.
- 메뉴 성혼 줄의 빨간 「!」(활성화 가능)는 열린 수에 넣지 않습니다.
- 잠김 0개(E6)는 성혼 탭 프레임 두 장 이상이거나 성혼 이름이 다섯 줄 이상 읽혔을 때만 믿습니다.

### 1-6. 전투 결과 (hud.py)
마지막 쇼케이스 앞 40초(모자라면 200초)를 1초에 한 장씩 보고, HUD 가 마지막으로 보인 순간의 값을 씁니다.

| 모드 | 읽는 값 | 판정 |
|---|---|---|
| 이상 중재 | 오른쪽 위 「소모 라운드」 배지 숫자(전처리 3가지 × 마지막 10장 다수결) | 0-Cycle 이면 0, 아니면 제출 수와 같아야 함. 세부 분류(0-Cycle / full stars / Clear)도 맞춰 봄 |
| 이상 중재 절망(Plight) | 왼쪽 행동 순서의 「⧗N \| x」 칸 | 소비 행동 수치 = 500 − (N × 100 + x) 가 제출 값과 같아야 함 |
| 종말의 환영 | 오른쪽 위 「남은 행동 수치」 | 점수 = 2000 + 남은 행동 수치(보스 처치 가정). 0 AV ↔ 2000 |

절망 칸은 OCR 이 모래시계를 「2」, 구분선을 「1」로 읽어 글만으로는 가를 수 없습니다(「20116」 = ⧗0 \| 16).
그래서 흰 글자 덩어리를 「모래시계 · 숫자 하나 · 가는 세로줄 · 숫자 1~3개」 꼴로 찾고 N 과 x 를 따로 잘라 읽습니다.
캐릭터 칸의 행동값 숫자는 구분선이 없어 걸리지 않습니다.

### 1-7. 보유 효과 (gp.py)
- 전투 전체를 1초에 네 장씩 봅니다(배너는 0.5초만 뜨기도 함). 오른쪽 가운데 띠에 「큰 흰 글자가 가로 셋 이상」
  있는 프레임만 OCR 하고, 배너 이름 12개 언어와 맞춥니다. 은랑 LV.999 는 위쪽 「…해킹」 안내도 1초에 한 번 봅니다.
- 제출 flags 에 있는데 발동하지 않았거나, flags 에 없는데 발동했으면 문제입니다. 편성에 없어도 계정 효과로 발동합니다.
- 카스토리스(revive)는 예외입니다. 제출에 있는데 배너를 못 찾으면 실제로 안 썼는지 도구가 놓쳤는지 가리지 않고 **CHECK** 로 보냅니다
  (다른 문제가 있어도 CHECK, 문제 목록은 그대로 적음).

### 1-8. 그 밖
- **UID:** 캐릭터 화면 왼쪽 아래 칸 OCR. 못 읽으면 감점.
- **시작 시각:** 재생 시작(링크의 `t=`) 뒤 1분 안에 전투 HUD 라벨이 보여야 합니다(한 런짜리).
- **팀 순서 확인(CHECK).** 첫째 자리 캐릭터가 4성이거나 개척자가 아닌 5성인데, 그 성혼이 2~4번 자리의 (4성도 개척자도 아닌) 캐릭터 누구보다 낮으면 CHECK 입니다(「First position X has a lower Eidolon than Y: confirm the team order」). 성은 게임 자료(`ExcelOutput/AvatarConfig.json`)의 Rarity, 개척자는 이름에 「Trailblazer」가 든 것입니다. 제출된 값만 씁니다.
- **빌리빌리 여러 파트:** 링크가 가리키는 파트(`?p=`)가 실전입니다. 파트끼리 섞지 않습니다(2파트와 3파트가 서로 다른 전투 · 빌드일 수 있음).

### 1-9. 신뢰도와 판정
신뢰도 = 100 − 감점(`tools/auto_judge.py` 의 `CONF`). 같은 영상이면 언제나 같은 값이 나옵니다.

| 감점 | 이유 |
|---|---|
| −100 | 영상 파일이 끝까지 디코드되지 않음 |
| −30 | 전투 끝 HUD 값을 못 읽음 |
| −20 | 중첩을 못 읽음 / 성혼을 못 읽음 |
| −15 | HUD 읽기 일치율 50% 미만 / 「미표시」인데 다른 캐릭터 화면도 덜 잡힘 |
| −10 | UID 못 읽음 / 재생 시작 1분 안에 전투를 못 봄 |
| −5 | 성혼을 한 장으로만 읽음(또는 두 장인데 흐림) / 애매한 노드 하나마다 / 활성화 가능 노드 / HUD 일치율 50~80% |
| −4 | 누구 화면인지 추정(소거 · 앞 화면)으로 정함 |
| −3 | 광추 이름 일치 0.7~0.9 |
| −2 | 누구 화면인지 근거 하나로만 약하게 맞음 |

- **REJECT:** 제출과 다른 것이 하나라도 있음(사유를 모두 적음)
- **CHECK:** 신뢰도 80 이하이거나 못 읽은 항목이 있음, 사람이 봐야 함
- **APPROVE:** 그 밖

### 1-10. 검증
제가 사람 눈으로 판정한 24건(승인 20, 거절 4)으로 시험했습니다.
- 승인 20건 → APPROVE 20 (신뢰도 81~100%)
- 거절 4건 → REJECT 4, 사유도 같음(광추 미표시 · 광추 다름 · 중첩 다름 · 행동 수치 다름)
- 한 건 판정 35~160초(가운데값 약 1분) + 메뉴 찾기 약 20초 + 내려받기

### 1-11. 아직 안 되는 것
- 허구 이야기(PF) 점수 · 사이클
- 결합 런(여러 사이드): 빌드는 전부 보지만 HUD 값 · 시작 시각은 첫 사이드만 봄. 사이드마다 보스가 맞는지 확인 안 함
- 한 영상에 여러 런이 있을 때 링크가 어느 전투인지는 `t=` 로 정합니다(1-12). 타임스탬프가 없으면 첫 전투로 보고, 같은 영상이 다른 건에도 있으면 CHECK 입니다
- 종말의 환영에서 보스를 못 잡은 경우(보스 HP 비율 점수)
- 같은 영상이 이미 사이트에 있는지 확인
- 「광추 · 성혼을 외부 빌드 카드로만 보여 준 경우」 구분

### 1-12. 영상 분석 파이프라인 (segment_pipeline.py)
제출은 한 전투에 대한 주장이고, 영상 하나에는 전투 · 재시작 · 쇼케이스가 여럿 있을 수 있습니다. 그래서 **영상 분석**(다시 쓸 수
있음)과 **건 판정**(주장마다)을 나눕니다. 설계 전체는 [REVIEWBOT_ANALYSIS_MIGRATION.md](REVIEWBOT_ANALYSIS_MIGRATION.md)(영어)에
있고, 요점은 이렇습니다.
- **영상 나눠 쓰기.** 주소가 달라도 같은 유튜브 영상은 한 번만 받고, 빌리빌리는 파트마다 따로입니다(`video_cache.py`,
  `work/video_cache/`).
- **전투 경계**(`scan_battle_boundaries.py`). 전투 HUD(일시정지 아이콘)를 2fps 로 따라가고, 시작 · 「전투 종료」 글은 HUD 가
  나타나거나 사라지는 곳에서만 OCR(13개 언어)로 읽습니다. 끝을 못 읽은 시도는 *미완*으로 두고 억지로 끝을 만들지 않습니다.
- **화면 영역.** 스캐너는 게임 화면만 봅니다. 어느 쪽이든(한쪽에만 있어도) 검은 띠, 그리고 화면을 흐리게 늘려 채운 띠(영상 하나에서 한 번,
  행 사이 경계가 계속 남는 곳으로 찾음)를 먼저 잘라 내고, HUD 는 720p 기준 크기(16:9 보다 좁은 화면은 높이, 넓은 화면은 폭 기준)로 맞춥니다.
  OCR 이 보는 곳(시작 · 종료 배너, 오른쪽 위 HUD 아이콘)은 모두 이 화면에서 자릅니다.
- **쇼케이스**(`scan_showcases.py`). 전투 사이 캐릭터 메뉴 구간. 여러 전투가 한 쇼케이스를 함께 쓰면(공용) 사람 확인 사유가 붙습니다.
- **전투 고르기.** 타임스탬프가 완전한 전투 하나 안에 있으면 그 전투, 전투 앞이면 90초 안의 다음 전투로 당겨 잡습니다. 후보가 둘 이상,
  어긋남 30초 초과, 미완 시도를 건너뜀, 타임스탬프가 쇼케이스 안 — 은 사람 확인 사유(또는 CHECK)입니다.
- **OCR 언어**는 빌드 화면으로 먼저 골라 경계 찾기에 넘기고, 애매하면 사람 확인 사유가 붙습니다.
- **이후 읽기는 모두 고른 구간 안에서만.** 전투 구간(HUD · UID · 보유 효과), 쇼케이스 구간(광추 · 성혼). 광추 · 중첩 · 성혼을 애매하게
  읽으면 같은 화면 둘레를 다시 읽고, 그래도 애매하면 불일치로 짐작하지 않고 CHECK 입니다.
- **긴 영상.** 20분까지는 보통. 20~60분은 서로 다른 두 건이 같은 영상을 가리킬 때만. 1시간 이상은 CHECK(`video_policy.py`,
  `work/video_cache/submission_references.json`).

파이프라인이 정하지 못하면(완전한 전투가 없음, 타임스탬프가 아무 데도 안 가리킴, 쇼케이스가 애매함) 까닭을 달아 **CHECK** 로 보내고
짐작하지 않습니다.

### 1-13. 그림 근거 (imgrec.py)
글 읽기에 기대지 않는 근거입니다(워터마크 · 자막 · 언어에 영향이 없음). 게임 그림은 `python tools/get_assets.py` 가 받습니다.
- **광추 카드.** 광추 화면의 카드 그림을 게임의 광추 그림과 맞춥니다(SIFT + RANSAC, 진짜는 맞은 점 150~230, 다른 광추는 10 안쪽).
  같은 광추를 낀 캐릭터는 중첩으로 짝을 맞춥니다.
- **성혼 노드 아이콘.** 켜진 노드는 그 캐릭터의 성혼 아이콘을, 잠긴 노드는 자물쇠를 보입니다. 아이콘 상관(켜짐 0.64~0.83, 잠김
  0.31~0.51)을 자물쇠 템플릿과 합쳐 켜진 노드 수를 고릅니다.
- **길 아이콘(머리글) · 속성 아이콘(상세 탭)** 은 **검증 전용**입니다. 읽은 캐릭터의 길 · 속성과 화면의 아이콘이 확정으로 다르면
  CHECK 로 보냅니다(「캐릭터를 제대로 읽었는지 확인」). 누구인지를 더 확실히 하는 근거로는 쓰지 않습니다.
- **모래시계 배지.** 행동 순서 줄이 길어 화면 밑으로 넘치면 모래시계 칸이 카운터가 든 작은 붉은 배지로 줄어듭니다. `hud.py` 가 이를 읽어
  허구 이야기의 카운터를 끝까지 따라갑니다.

---

## 2. 설치

### 2-1. 필요한 것
- Python 3.11 이상(3.14 에서 씀)
- Node.js(yt-dlp 가 YouTube 에서 쓰고, `build_eidolon_names.mjs` 를 돌릴 때)
- 디스크: 영상 한 편 100~300MB

```bash
pip install -r requirements.txt
# Windows 에서 그래픽카드를 쓰려면: pip uninstall onnxruntime && pip install onnxruntime-directml
python tools/get_models.py          # OCR 모델(약 125MB) → auto/models/
python tools/get_assets.py          # imgrec.py 가 쓰는 게임 그림(2-2 다음에) → data/
```

`get_assets.py` 는 2-2 의 게임 자료가 먼저 있어야 합니다(성혼 아이콘을 `ExcelOutput/AvatarRankConfig.json` 으로 찾음). 그림은 Hugging Face 데이터셋 `fffffffff1/assets`(최신) · `fffffffff1/imageassets`(정식)에서 받고, 이미 있는 파일은 건너뜁니다(`--force` 면 다시). 그림이 없으면 그림 근거만 빠지고 글 · 자물쇠 템플릿으로 판정합니다.

ffmpeg 는 `imageio-ffmpeg` 가 가진 것을 씁니다. 다른 것을 쓰려면 환경 변수 `FFMPEG`, yt-dlp 는 `YTDLP` 로 정합니다
(`tools/paths.py`).

### 2-2. 게임 자료
캐릭터 · 광추 · 성혼 이름을 13개 언어로 맞추려면 [Dimbreath TurnBasedGameData](https://github.com/DimbreathBot/TurnBasedGameData)
의 TextMap 이 필요합니다. 크므로 필요한 폴더만 받습니다.

```bash
git clone --filter=blob:none --sparse https://github.com/DimbreathBot/TurnBasedGameData data/TurnBasedGameData
cd data/TurnBasedGameData && git sparse-checkout set TextMap ExcelOutput && cd ../..
# tools 는 data/TextMap · data/ExcelOutput 을 본다. 다른 곳에 두었으면 환경 변수로:
#   HSR_TEXTMAP=data/TurnBasedGameData/TextMap  HSR_EXCEL=data/TurnBasedGameData/ExcelOutput
```

새 캐릭터가 나오면 성혼 이름 표를 다시 만듭니다.
```bash
node tools/build_eidolon_names.mjs   # → tools/eidolon_names.json
```

### 2-3. config.json
`config.example.json` 을 `config.json` 으로 복사해 채웁니다. **이 파일은 깃에 올리지 않습니다**(.gitignore).

| 키 | 쓰는 곳 |
|---|---|
| `discord_webhook` | 검토 보고(`tools/notify.py`, `run_queue.py --webhook review`) |
| `question_webhook` | 질문 · 시험 결과(`tools/ask.py`, `run_queue.py --webhook question`) |
| `mod_token` · `mod_refresh_token` · `supabase_url` · `supabase_anon_key` | 사이트 API(`tools/mod_api.py`) |
| `legacy_gates`(선택, `true`) | `run_queue.py`: 타임스탬프 링크 · 한 영상에 건이 여럿이면 무조건 CHECK 로 보내던 옛 규칙으로 돌아감 |
| `ytdlp_cookies_from_browser`(선택, 예: `"firefox"`) | `prep.py`: yt-dlp 에 `--cookies-from-browser` 를 준다(로그인이 필요한 영상). 환경 변수 `YTDLP_COOKIES_BROWSER` 도 같음 |

환경 변수 `DISCORD_WEBHOOK_URL` 은 `discord_webhook`(검토 보고용)만 바꿉니다.

### 2-4. 폴더
```
tools/        도구(아래 「3. 파일」)
auto/         OCR 감싸개(ocr.py) · 이름 찾기(names.py) · models/(받은 OCR 모델)
data/         게임 자료(올리지 않음)
runs/<rev>/   건마다 영상 · 중간 결과 · 판정(올리지 않음)
work/         대기열 · 결과 모음(올리지 않음)
```

### 2-5. 토큰 얻기 (DevTools 자동 조종 없이)
사이트는 Discord 로그인 뒤 Supabase 세션을 씁니다. 처음 한 번만 브라우저에서 꺼냅니다.
1. 브라우저로 theherta.com 에 검토자 계정으로 로그인합니다.
2. F12 → Application(응용 프로그램) → Local Storage(또는 Cookies) → `https://theherta.com` 에서
   이름이 `sb-<project>-auth-token` 인 값을 엽니다. 그 안의 `access_token` → `mod_token`,
   `refresh_token` → `mod_refresh_token` 에 넣습니다.
3. `<project>` 부분으로 `supabase_url` = `https://<project>.supabase.co` 를 만듭니다.
4. F12 → Network 에서 `supabase.co` 로 가는 요청 하나를 열어 요청 헤더 `apikey` 값을 `supabase_anon_key` 에 넣습니다
   (공개 키입니다).

이후로는 `mod_api.py` 가 만료 때마다 refresh token 으로 새 토큰을 받아 `config.json` 에 적습니다.
토큰을 한 번만 쓸 거라면 환경 변수 `THEHERTA_TOKEN` 에 access token 만 넣어도 됩니다(새로 받기는 안 함).

---

## 3. 실행

### 3-1. 대기열에서 차례로
```bash
python tools/run_queue.py --fetch --limit 5                 # 대기열 받고 아무도 안 잡은 5건 판정
python tools/run_queue.py --fetch --limit 5 --claim         # 판정 전에 「검토 중」 표시
python tools/run_queue.py rev_abc123 --webhook question     # 한 건만, 결과를 질문 웹후크로
```
디스코드 보고는 디스코드 봇의 제출 임베드와 같은 짜임의 임베드입니다(색 = 판정: 초록 APPROVE, 빨강 REJECT, 노랑 CHECK,
제목을 누르면 검토 페이지). 터미널 출력 예:
```
REJECT · 100% confidence
**Author:** …
**Season:** 3.6
**Status:** Not decided (human)
[❌ Problems]
• Cerydra Light Cone mismatch (submitted 'Dance! Dance! Dance!', video '… 황금 피가 새긴 시대 …')
• Cerydra Superimposition mismatch (submitted S5, video S1)
[MOC | Gepard | 0-Cycle | 0 Cycles | 5L / 1S]
✅ **Firefly** (E2S1) — *Whereabouts Should Dreams Rest*
└ LC [3:50](https://youtu.be/…?t=230) · E [4:01](https://youtu.be/…?t=241)
❌ **Cerydra** (E0S5) — *Dance! Dance! Dance!*
└ LC [4:10](https://youtu.be/…?t=250) · E [4:20](https://youtu.be/…?t=260) · **video LC '… 황금 피가 새긴 시대 …'** · **video S1**
[Battle (HUD)]
• Cycles (HUD): 0 at Battle Over
[Links]
[Video](https://youtu.be/…) · [Showcase 3:49](https://youtu.be/…&t=229) · [Review](https://theherta.com/mod?review=rev_…)
ID: run_1nl1xos  •  Review ID: rev_…
```

분석하지 않고 곧바로 **CHECK** 로 보내는 건: 합친 제출(한 건에 런 여럿), 같은 영상이 다른 건에도 있는데 이 링크에 타임스탬프가 없는 것,
20분 넘는 영상(1-12), 못 받은 영상. 보고에 시트가 있으면 빌드 시트와 전투의 처음 · 끝 쪽 한 장씩이 붙습니다.

### 3-2. 단계별로
```bash
python tools/mod_api.py queue                 # → work/queue.json
HQ_QUEUE=work/queue.json python tools/prep.py rev_abc123
python tools/tabs.py rev_abc123 0             # 영상 전체, 또는 tabs.py <rev> <파트> <시작 초> <길이 초>
                                              # (run_queue.py 는 먼저 segment_pipeline.prepare() 로 segment_selection.json 을 쓴다)
python tools/auto_judge.py rev_abc123         # → runs/rev_abc123/auto.json
python tools/auto_judge.py rev_abc123 --reuse # 빌드 읽기만 다시(HUD · 보유 효과 결과는 auto_cache.json 재사용)
```

### 3-3. 사이트에 결정 보내기
```bash
python tools/mod_api.py decide rev_abc123 approve            # 보낼 내용만 보여 줌
python tools/mod_api.py decide rev_abc123 approve --yes      # 실제로 보냄
python tools/mod_api.py decide rev_abc123 reject "Hyacine Light Cone Superimposition not shown" --yes
```
거절 사유는 `reject_templates.md` 의 꼴을 따르고, 영상 속 게임 언어로(한 · 영 · 중 · 일, 그 밖은 영어) 한 줄로 씁니다.
문제가 여럿이면 「 / 」로 잇습니다.

### 3-4. AI 에이전트와 함께 쓰는 방식(이전 방식)
Claude Code 같은 에이전트가 Chrome DevTools 로 검토 페이지를 열고, `tools/run_item.py` 가 만든 시트(광추 · 성혼 프레임
`tabs<i>/sheet.jpg`, 보유 효과 4fps 시트 `gpf<i>_*/`, 전체 개요 `ov<i>.jpg`)를 사람처럼 보고 판정하던 방식입니다.
지금은 `auto_judge.py` 가 같은 판정을 AI 없이 냅니다. 시트 도구(`scan_sheet.sh`, `gp_fast.sh`, `overview.sh`, `hdr_strip.sh`,
`top_sheet.sh`, `frames.py` 등)는 사람이 근거 장면을 직접 확인할 때 씁니다.

---

### 3-5. 로컬 파일 분석 (사이트 없이)
`tools/run_local.py` 는 사이트 대기열 대신 제출 JSON 파일로 같은 분석을 돌리고 결과를 디스코드로 보낼 수 있습니다. 영상은 링크 또는 로컬
MP4(`local_battle_video`, `local_showcase_video`)로 줍니다.
```bash
# data/ 와 config.json 을 먼저 채운다(2-1 ~ 2-3). 항목은 submission.example.json 참고
python tools/run_local.py submissions.json --no-webhook          # 분석하고 보고를 찍는다
python tools/run_local.py submissions.json --watch --poll 10     # 새 항목을 기다리며 디스코드로 보낸다
python tools/run_local.py submissions.json --validate-only
```
윈도우에서는 `startreviews.bat` 가 게임 자료 경로(`data\TurnBasedGameData\...`)를 정해 같은 일을 합니다. `start-folder-opener.bat` 는
`tools/folder_opener.py`(127.0.0.1 만 받는 작은 웹 서버, 무작위 토큰은 `work/folder_opener_token.txt`)를 띄워 보고의 링크로 실행 폴더를
열거나 영상을 재생합니다. `submissions.json` 은 각자 입력이라 깃에 올리지 않습니다.

### 3-6. 여러 건을 한꺼번에 검토
```bash
python tools/run_queue.py --fetch --limit 10 --jobs 3 --downloads 3 --webhook review
```
- `--downloads M`: 분석 자리를 기다리는 건들의 영상을 최대 M 개까지 미리 받습니다(`prep.py`, 네트워크가 병목). 분석이 끝나면 다음 건의
  영상이 이미 디스크에 있습니다.
- `--jobs N`: 최대 N 건을 동시에 분석합니다. 건마다 따로 프로세스(`run_queue.py --worker <rev>`)라 서로의 상태를 건드리지 않습니다.
  워커마다 OCR 모델을 올리고 영상을 디코드하므로 RAM · CPU 가 한계입니다(2~3 부터 시작해 메모리를 보세요). 빌드 읽기는 기본으로 GPU 를
  쓰고, 워커끼리 GPU 를 다투면 `OCR_GPU=0` 으로 끕니다.
- 같은 영상을 가리키는 건은 차례로 돕니다(받은 영상과 `work/video_cache` 의 전투 · 쇼케이스 캐시를 함께 쓰므로).
- 보고 · `work/results.jsonl` · 디스코드 게시는 메인 프로세스가 한 건씩 씁니다. 순서는 대기열 순이 아니라 분석이 끝나는 순입니다. 건별 로그는
  `runs/<rev>/worker.log` · `prefetch.log`.
- 기본: 여러 건이면 분석 2건 · 영상 받기 2건을 동시에 합니다(`config.json` 의 `jobs` · `downloads` 로 기본값을 바꿈). 한 건씩은
  `--jobs 1 --downloads 0`.
- `--claim` 은 그 건의 분석을 시작할 때 「검토 중」을 표시합니다. 사이트의 표시는 1분뿐이고 여기서는 갱신하지 않습니다(5절).

### 3-7. 요약 페이지 (HTML)
여러 건 판정이 끝나면 `run_queue.py` 가 `work/summary_<시각>.html`(그리고 `work/summary_latest.html`)을 만들고 경로를 찍습니다. 판정별 묶음(CHECK,
REJECT, APPROVE 순)에 카드로 나열합니다: 캐릭터 그림 + E / S 배지, 사이클 · 점수 알약, 하위 분류, 보스, Ltd / Std 수, 날짜 · 플랫폼, 사유. 모양은
theherta.com 기록 목록(archive)을 따릅니다. `--no-summary` 로 끄고, `python tools/summary_html.py [rev_id ...]` 로 손으로 만듭니다.
- 캐릭터 · 광추 그림은 페이지를 열 때 `https://theherta.com/px_char/<이름>.png` · `px_lc/<이름>.png` 에서 불러옵니다.
- 사이트와 똑같은 모양으로 하려면 사이트의 archive 페이지를 본인 브라우저에서 열고 `tools/ui_dump_console.js` 를 DevTools 콘솔에 붙여 넣어 저장(`theherta-ui-dump.json` 이 내려받아짐)한 뒤
  `python tools/extract_ui_theme.py <덤프.json>` 을 돌립니다. `data/ui_theme/site.css`(사이트 자신의 스타일시트라 깃에 올리지 않음)가 만들어집니다.
  없으면 같은 색 · 모양을 직접 쓴 작은 스타일로 그립니다.

## 4. 파일

| 파일 | 하는 일 |
|---|---|
| `tools/paths.py` | 경로 · ffmpeg · yt-dlp 찾기(환경 변수로 바꿈) |
| `tools/mod_api.py` | 사이트 검토 API(대기열 · 검토 중 표시 · 결정) |
| `tools/run_queue.py` | 대기열 여러 건을 받기 → 영상 나누기 → 전투 · 쇼케이스 고르기 → 메뉴 찾기 → 판정 |
| `tools/run_local.py` | 같은 일을 로컬 제출 JSON 으로(3-5) |
| `tools/segment_pipeline.py` | 영상별 전투 · 쇼케이스 경계 캐시, 타임스탬프로 전투 고르기, 고른 구간만 읽기 |
| `tools/scan_battle_boundaries.py`(`_gated`) · `scan_showcases.py` | 전투 시작 · 끝 찾기(HUD + 글 OCR) · 쇼케이스 찾기 |
| `tools/video_cache.py` · `video_policy.py` | 받은 영상 · 추출 결과 나눠 쓰기 · 긴 영상 받아 주기 |
| `tools/summary_html.py` · `extract_ui_theme.py` | 한 묶음의 요약 페이지(3-7) · 저장한 사이트 페이지에서 스타일 뽑기 |
| `tools/battle_sheets.py` · `report.py` | 고른 전투 시트 · 디스코드 보고 |
| `tools/imgrec.py` · `get_assets.py` | 그림 근거(1-13) · 거기에 필요한 게임 그림 받기 |
| `tools/folder_opener.py` · `benchmark_*.py` · `test_showcase_builds.py` | 로컬 실행 폴더 열기 · 시간 견주기 · 쇼케이스 시험 |
| `tools/prep.py` | 영상 받기(파트 · 화질 다시 받기) |
| `tools/tabs.py` | 캐릭터 화면 구간 · 광추 / 성혼 프레임 |
| `tools/judge.py` | 누구 화면인지 · 광추 · 중첩 · 성혼 |
| `tools/hud.py` | 전투 끝 HUD 값 |
| `tools/gp.py` | 보유 효과 배너 |
| `tools/auto_judge.py` | 모두 합쳐 판정 · 신뢰도 |
| `tools/build_eidolon_names.mjs` | 성혼 이름 표 만들기 |
| `tools/get_models.py` | OCR 모델 받기 |
| `tools/ask.py` · `tools/notify.py` · `tools/webhook.py` | 디스코드 웹후크 |
| `tools/run_item.py` · `confidence.py` · `*.sh` · `frames.py` … | 사람(또는 AI)이 볼 시트 만들기 |
| `auto/ocr.py` | RapidOCR + 언어별 PP-OCRv5 인식 모델. 빌드 읽기만 GPU(DirectML), 나머지는 CPU |
| `auto/names.py` | 영어 게임 이름 → 언어별 TextMap 이름 |
| `reject_templates.md` | 거절 사유 템플릿(언어별) |

## 5. 여러 사람이 쓸 때 (대책이 필요함 — 아직 안 했음)
위의 모든 것은 한 사람이 한 컴퓨터에서 쓴다고 가정합니다. 여러 검토자(또는 컴퓨터)가 같은 대기열에 이 봇을 돌리면 아래 문제가 생깁니다.
그렇게 쓰기 전에 처리해야 해서 적어 둡니다.
1. **같은 건을 둘이 검토.** 사이트의 「검토 중」 표시는 1분이고 `run_queue.py` 는 한 번만 겁니다. 두 실행기가 같은 건을 집을 수 있습니다.
   판정 중 계속 갱신하는 잡기(heartbeat), 보고를 보내기 직전의 잡기 확인, 또는 누가 무엇을 하는지 나눠 보는 목록이 필요합니다.
2. **컴퓨터끼리 아무것도 나누지 않음.** `runs/` 와 `work/video_cache` 가 각자 로컬이라 같은 영상을 컴퓨터마다 받고 다시 스캔합니다. 긴 영상 규칙
   (「서로 다른 두 건이 이 영상을 가리킬 때」, `work/video_cache/submission_references.json`)도 그 컴퓨터가 본 건만 셉니다. 공용 캐시나
   중앙 서비스가 필요합니다.
3. **레지스트리 파일은 쓰는 쪽이 하나.** `video_policy.py` 와 캐시 게시는 컴퓨터 하나에 실행기 하나를 가정합니다. 공용 디스크에서 여러
   실행기가 돌면 잠금(또는 데이터베이스)이 필요합니다.
4. **보고 중복 · 순서.** 두 실행기가 같은 건을 두 번 올리고, 병렬 실행은 끝나는 순서로 올립니다. 보고에 건 식별자를 고정으로 싣고 이미 올렸으면
   건너뛰어야 합니다.
5. **인증 정보.** 사람마다 자기 검토자 토큰을 써야 합니다. 한 세션 토큰을 여럿이 나눠 쓰는 것은 위험합니다. 봇용 API 키(0-2절)가 해결책입니다.
6. **버전이 다르면 판정이 다름.** 모두 같은 커밋을 써야 합니다. 보고에 커밋이 아직 안 나옵니다.
7. **자원.** 건마다 `runs/` 에 100~300MB 가 남고 캐시가 자랍니다. 누가 언제 무엇을 지울지 정해야 합니다.
8. **디스코드 한도.** 웹후크 하나는 호출 한도가 있습니다(전송기는 429/5xx 에서 다시 시도). 한 채널에 실행기가 여럿이면 게시자를 하나로 하거나
   채널을 나눠야 합니다.

## 6. 출처 · 라이선스
- OCR 모델: [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-OCRv5(Apache-2.0)의 ONNX 변환
  [monkt/paddleocr-onnx](https://huggingface.co/monkt/paddleocr-onnx)
- 게임 글: 붕괴: 스타레일 © HoYoverse, [Dimbreath](https://github.com/DimbreathBot/TurnBasedGameData) 덤프
