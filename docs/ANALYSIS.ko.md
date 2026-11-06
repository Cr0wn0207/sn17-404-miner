# 404-GEN Subnet 17: 라운드 3 로직 분석

조사 기준: 2026-11-07, Asia/Vladivostok(UTC+10). 공식 코드 commit `3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb`, 공개 대회 상태 commit `0414b1285201c088de9c7f7080ce60fd7d30d9c5`. 상태·일정은 이후 바뀔 수 있으므로 실행 직전 다시 확인해야 합니다.

## 1. 무엇을 채굴하는가

Bittensor netuid 17의 이미지→절차적 3D 생성 대회입니다. 마이너가 제공하는 것은 특정 장면 한 개나 모델 가중치가 아니라, 공개 전 고정한 Python 생성 프로그램입니다. 입력은 PNG와 공통 seed, 출력은 객체를 만드는 자급식 Three.js 코드입니다. 마이너는 자신의 인증으로 생성 비용을 부담하고 witness에 증거가 남는 모델 호출과 렌더를 사용합니다.

`Competitions/competition3.md`의 **Competition 3은 규칙 버전/대회 종류**이며 `rounds/3`의 **라운드 3은 그 대회의 회차**입니다. 두 숫자를 혼동하면 안 됩니다. 현재 규칙은 승인된 폐쇄형 OpenAI 모델을 사용하는 image-to-Three.js입니다. 오래된 competition0/1/2 설명의 GPU·모델 학습 지침을 그대로 적용하지 않습니다.

제출은 공개 저장소의 `main.py`와 모든 보조 소스·데이터 및 전체 40자리 SHA입니다. Finney netuid 17 등록 hotkey와 100-alpha lock이 필요합니다. 체인 commitment는 `repo`와 `commit`을 지정합니다. 과제·seed 공개 후 특정 이미지에 맞추어 프로그램을 바꾸는 제출은 허용되지 않습니다.

근거: [Competition 3](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/Competitions/competition3.md), [Miner Guide](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/miner-reference/README.md).

## 2. 라운드 3의 실제 상태

확인한 `state.json`은 `current_round=3`, `stage=open`, 다음 단계 ETA `2026-11-07T08:00:00Z`입니다. 사용자 시간대에서는 **2026-11-07 18:00(UTC+10)**입니다. 조사 시 `rounds/3`에는 `schedule.json`만 있고 과제·seed는 없습니다. 따라서 실제 라운드 3 과제의 완성 출력이나 우승률을 지금 검증했다고 할 수 없습니다.

| 항목 | 공개 값 |
|---|---|
| earliest_reveal_block | 9424094 |
| latest_reveal_block | 9452891 |
| generation_deadline_block | 9460091 |
| 과제 수 | 128 |
| 이전 라운드 유지 과제 수 | 32 |
| 새로 뽑는 과제 수 | 96 |
| 생성 창 | 1440분(24시간) |
| 기본 회차 간격 | 4일 |
| 리더 교체 margin | 0.07 |

ETA를 단순 적용하면 생성 종료는 11월 8일 18:00 UTC+10 부근입니다. **블록 기준 schedule이 실제 판단 기준**이며 벽시계 ETA는 확정 마감이 아닙니다. 이전 공개 이미지 32개가 유지되더라도 96개의 미지 이미지가 있으므로 특정 이미지 전용 파일보다 일반적인 생성기의 품질이 필요합니다.

직전 라운드 2 승자는 `SmoothTight/newvictor@0f4bc9370c083b8808e4d78645fe3892e67338a2`, hotkey `5G3s1WKn57n3hB2HCpijGtpTNeRBFyYHj7WfxSH47UGFqP7w`입니다. `leader.json`의 마지막 전이는 effective_block 9452891부터 적용됩니다. 조회 블록에서 이미 활성인지와 다음 회차에 지정된 리더인지는 구분해야 합니다.

근거: [state](https://github.com/404-Repo/404-active-competition/blob/0414b1285201c088de9c7f7080ce60fd7d30d9c5/state.json), [config](https://github.com/404-Repo/404-active-competition/blob/0414b1285201c088de9c7f7080ce60fd7d30d9c5/config.json), [round 3 schedule](https://github.com/404-Repo/404-active-competition/blob/0414b1285201c088de9c7f7080ce60fd7d30d9c5/rounds/3/schedule.json), [round 2 winner](https://github.com/404-Repo/404-active-competition/blob/0414b1285201c088de9c7f7080ce60fd7d30d9c5/rounds/2/winner.json).

## 3. 서비스별 흐름

`OPEN → MINER_GENERATION → COLLECTING → DUELS → FINALIZING → OPEN` 순서입니다.

1. **submission-collector**가 제출 창과 공개·생성 마감을 관리합니다. 등록·잠금·commitment를 확인하고 해당 라운드 이미지·seed를 확정합니다.
2. **miner runtime / witness gateway / Pod**가 인증된 마이너의 모델 요청·응답과 렌더 관찰을 보관합니다. SDK batch runner는 미완료 과제·캡처를 복구하고, 함수가 반환한 정확한 JS 또는 `None`을 저장·제출합니다.
3. **render-service-js**가 JS의 AST, 금지 API, 실행 제한 및 출력 씬을 검사한 뒤 Chromium/WebGL로 다각도 이미지를 만듭니다. 최종 bundle에는 white 8개, gray 4개, grid와 DINOv3 embeddings가 들어갑니다.
4. **judge-service**가 이미지별 pairwise duel을 묶어 miner 대 miner match를 계산합니다. 기존 리더는 운영자가 고정된 Python 소스와 새 과제·seed로 다시 실행합니다.
5. **validator**는 녹화된 모델 응답으로 Python 프로그램을 재실행합니다. 새 추론 없이 요청·출력·렌더·예산의 일치를 검증합니다. **source auditor**의 별도 판정도 필요합니다.
6. **round-manager**가 검증된 승자를 기록하고 다음 회차를 엽니다. 서로 다른 소스 정체성의 새 승자는 weight 1.0, 다음 시작 블록부터 적용됩니다. 동일 repo+commit은 다른 hotkey여도 방어로 간주합니다.
7. **weights-setter**가 현재 블록의 리더를 찾아 subnet owner와 리더에 가중치를 배분합니다. 현재 `_calculate_weights`는 owner=1−leader_weight입니다. README의 방어 시 decay 서술과 달리 현재 round-manager 코드는 방어 시 기존 weight를 그대로 유지합니다. 또한 이 코드만으로 실제 TAO 수익을 계산할 수는 없습니다.

근거: [timeline](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/judge-service/judge_service/timeline.py), [finalization](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/round-manager/round_manager/finalize_round.py), [weights](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/weights-setter/weights_service.py).

## 4. 이미지별 심사: S1~S4

현재 코드 기본 VLM ID는 `glm-4.6v-flash`입니다. 실제 운영 모델은 변경 가능하며 공지의 모델 벤치마킹이 곧 특정 모델 배포를 증명하지는 않습니다.

| 단계 | 검사 | 주요 로직 |
|---|---|---|
| S1 | 정면 계열 4시점의 참고 이미지 유사도 | 각 시점 AB·BA로 순서 교환, 0~10 mismatch penalty. 가중 차이가 0.7 이하이면 draw. 둘 다 매우 나쁘거나 시점별 판단이 충분히 일치하지 않아도 다음 단계로 이동. 명확한 승패면 즉시 반환 |
| S2 best view | 각 모델의 참고 이미지에 가장 가까운 한 시점 | DINOv3 embeddings가 시점을 고르고 VLM이 AB·BA 비교. 일반 투표 최소 penalty gap 1.0 |
| S2 artifact | 4시점 grid의 재료·색상·결함 | 불필요한 상자/바닥, 잘못된 핵심 색, 노이즈·이음새, 빠진 구조 디테일 비교 |
| S2 checklist | 참고 이미지의 구체적 4~7 특징 | yes=2, partial=1, no=0, 주 객체 정답 bonus=3. 일반 gap 2 이상. 강한 best-view/checklist 차이는 별도 우선 규칙, 그 외 3개 중 2표 합의 |
| S3 | 회색 배경에서의 재판정 | S2가 draw이고 pale·grayish foreground 게이트가 켜질 때만 실행. AB·BA 차이가 충분해야 결정 |
| S4 | 오른쪽·뒤·왼쪽·위의 3D 일관성 | 4개 중 3개 이상이 garbage이면 해당 모델의 승리→draw 또는 draw→패배로 한 단계 하향 |

**S1에서 승패가 나면 S4까지 가지 않습니다.** 파일 상단의 S4 always라는 주석보다 실제 `evaluate_duel`의 조기 반환이 우선입니다. S2/S3 경로에 들어가면 S4를 실행합니다. 정면을 우선 개선하되 뒤가 텅 빈 billboard로 만드는 전략은 규칙·source audit·측면 검사 모두에 문제가 됩니다.

라운드 2에 저장된 모든 `duels_*.json`을 합산하면 20,608개의 duel 기록 중 S1 결정이 10,867건(약 52.73%), S3 gate 미발동 draw가 6,673건(약 32.38%)입니다. 이는 여러 miner 대결에서 같은 이미지가 반복된 기록이지 독립 표본 20,608개가 아닙니다. 정면 품질과 draw를 승리로 바꾸는 식별 디테일에 집중할 근거로 사용하며 미래 승률로 해석하지 않습니다.

근거: [judge implementation](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/judge-service/judge_service/judges/multi_stage.py).

## 5. 전체 승리와 검증

각 이미지에서 challenger 승리=+1, 패배=−1, draw/skipped=0입니다.

`margin = (wins − losses) / number_of_prompt_duels`

128개이면 `ceil(128 × .07)=9`이므로 **순승수 9개 이상**이 필요합니다. 9승 0패 119무는 통과할 수 있고, 65승 63패는 순승수 2라 통과하지 못합니다. 무승부를 분모에서 빼지 않으므로 단순 승률 53.5%라는 표현은 부정확합니다. 128개를 전부 낸다는 전제하의 계산입니다.

먼저 기존 리더에 대한 margin을 만족해야 자격 후보가 됩니다. collector 순서대로 현재 방어자와 맞붙는 timeline을 재구성합니다. 후보가 기존 리더를 이겼다는 사실만으로 최종 1위가 되는 것은 아닙니다. 중간 승자의 replay 또는 audit이 실패하면 해당 후보를 제거하고 캐시된 match로 timeline을 다시 계산합니다. 필요한 결과가 아직 없으면 대기합니다. 최종 생존 timeline의 리더들이 검증되어야 확정됩니다.

근거: [match scoring](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/judge-service/judge_service/match_execution.py), [timeline eligibility](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/judge-service/judge_service/timeline.py).

## 6. 생성과 예산 제약

과제마다 60회·5,000,000 credits 한도입니다. 1 credit=$0.000001 Standard API 환산입니다. 폐기·개선·비교·reasoning 토큰을 모두 포함하고 cached input에도 입력 전체 요율을 적용합니다. 과제 사이의 예산 이전은 불가합니다. Flex는 금지이며 Standard/Fast/Ultrafast는 Standard 요율로 계산합니다.

| 모델 | 입력 credits/token | 출력 credits/token |
|---|---:|---:|
| gpt-6-astra | 10 | 50 |
| gpt-6.1-sol | 2 | 10 |
| gpt-6.1-terra | 1 | 5 |
| gpt-6-luna | 0.10 | 0.50 |

1개 요청의 입력이 **272,000 초과**이면 해당 요청 전체가 long-context 요율입니다. 예를 들어 Terra의 long 요율은 입력 2, 출력 7.5입니다. 검증된 usage에 reasoning output이 이미 포함되므로 중복 가산하지 않습니다. provider HTTP 오류와 쓸 수 없는 실패 응답의 예외 규칙은 공식 가이드를 따르며, usable incomplete response는 usage가 있으면 계산에 들어갑니다.

JS는 정확히 하나의 동기 default export, `generate(THREE)`이며 Y-up, +Z-front입니다. 한도는 파일 1MiB, literal 50KB, 실행 5초, heap 256MB, vertex 250,000, draws 200, 깊이 32, instances 50,000, texture 4MiB, 모든 축 bbox ±0.5입니다. import·외부 자산·shader·DOM·network·JS randomness는 금지입니다. 이미지 픽셀을 bake한 texture 대신 절차적 geometry·texture를 만듭니다.

공식 API 호출은 제공된 witness만 사용해야 합니다. **OpenRouter 직접 호출 로그는 승인된 witness 증거가 아니므로 공식 생성·replay에 사용할 수 없습니다.** 개발 실험은 별도 도구에서만 수행합니다. Python이 seed·이미지·녹화 응답 외에 시계, UUID, 디렉터리 순서, 환경변수로 생성 분기를 바꾸면 replay가 달라질 수 있습니다.

근거: [tariff](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/miner-reference/budgets/pricing.json), [output limits](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/miner-reference/output_specifications.md).

## 7. 첨부 공지의 의미와 이번 구현

중립 조명은 금속이 반사할 실제 환경을 제공하므로, 종전 studio 환경에서 은·금이 검게 뭉개지던 문제를 줄입니다. 현재 `shared/subnet_common/render.py`는 최종 view에 `lighting=neutral`을 명시합니다. 반면 SDK `RenderOptions()` 자체의 기본값은 여전히 studio이므로 미리보기에도 **명시적으로 neutral**을 넣어야 합니다. 모델에 금속을 무조건 비금속으로 바꾸라고 지시하는 과거 우회는 이 조건에서 적합하지 않습니다.

README의 일부 렌더러 버전 표기와 package의 최신 버전은 다릅니다(가이드 0.4.8, 현재 package 0.4.10). 로컬 검증은 현재 체크아웃으로 진행하지만 공식 pinned build와 완전히 같은 환경이라는 뜻은 아닙니다. 실제 witness가 제공하는 미리보기와 최종 저장이 최종 기준입니다.

이번 구현은 7개 특징 분석, 독립 초안 6개, 중립 조명 12시점 렌더, AB/BA 선택, Astra 개선, Sol 개선, 부모 보존을 사용합니다. 정확한 Decimal ledger와 단계 전체 사전 예산을 둡니다. 기존 우승자의 공개 소스에는 6개 초안·다단계 개선·자세 탐색 등이 이미 있으므로 단순 후보 수만으로 우위를 주장하지 않습니다. 이번 코드는 공개 경쟁자 소스를 복제하지 않고 작성했으며, 실제 우위는 실험 결과와 공식 duel로 입증해야 합니다.

## 8. 사용자가 실제로 해야 하는 마이너 미션

1. 공개 전에 이 생성기의 소스·지원 파일을 본인 GitHub에 게시하고 40자리 SHA를 고정합니다.
2. 등록된 netuid 17 hotkey와 잠금 상태를 확인하고 repo/commit commitment를 시간 안에 공개합니다.
3. 공식 OpenAI API 또는 Codex 구독 인증과 witness 설정을 준비합니다.
4. 라운드 3 과제·seed가 공개되면 SHA를 바꾸지 않고 128개 과제를 SDK batch로 실행합니다.
5. deadline 전에 반환 결과가 Pod에 최종 저장되었는지 확인하고 미완료 capture는 동일 요청으로 복구합니다.
6. DUELS와 validation/source audit 결과를 확인합니다. 화질이 좋아도 재현·예산·감사 실패이면 리더가 될 수 없습니다.

이 작업에서 chain commitment, alpha lock, 등록, 원격 GitHub 게시를 실행하지는 않았습니다. 사용할 저장소·wallet/hotkey와 공식 인증이 지정되어야 해당 실행을 특정할 수 있습니다.
