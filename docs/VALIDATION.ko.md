# 검증 결과와 현재 한계

기준일: 2026-11-07, Asia/Vladivostok. 소스는 `main.py`의 async entry point와 공식 witness/runtime 배치 인터페이스로 구현했습니다. 과제별 후보 생성과 선택은 seed·이미지·고정 소스·기록된 응답·렌더만 사용합니다.

## 확인한 결과

| 확인 | 결과 | 범위 |
|---|---|---|
| Python invariant tests | 18/18 통과 | 요금 경계, reasoning/cached input 정산, 호출·렌더·출력 재현, 오류 전파, 1회 복구, AB/BA 동점, 잘못된 선택 응답 배제 |
| Ruff 정적 검사·포맷 | 통과 | main, miner, tools, tests |
| 공식 SDK 로딩/CLI | `main.py --help` 성공 | witness 0.2.17, renderer 0.1.4, runtime 0.1.5 |
| dependency check | 통과 | Python 3.13.15, 공식 direct dependency 버전 |
| 실제 생성 초안 | 10개 | 시계 2, SUV 1, 축음기 1, 호박 6 |
| 공식 JS validator | 10/10 통과 | AST, API 제한, 실제 실행, 씬 자원·경계 검사 |
| 중립 조명 미리보기 | 10/10 성공 | 각 초안당 white-front 4, gray-front 4, side/back/top 4 |
| 실제 기록 초안 단계 재실행 | 통과 | 호박 후보 6개, 24개 호출/렌더 관찰, 동일 소스 hash·순서·정산 |
| 새 렌더 재현 | 4/4 바이트 일치 | 시계·SUV·축음기·호박 각각 대표 초안의 white-front 미리보기 |
| 고해상도 정면 렌더 | 4/4 성공 | 대표 초안당 1024px의 정면 4시점 |

원자료: [JavaScript validation](javascript-validation.json), [실제 초안 단계 replay](initial-stage-replay.json), [렌더 재현 검사](render-checks.json).

10개 초안의 vertex 수는 50,938~232,582, draw calls는 4~74, texture 데이터는 최대 1,703,936 bytes였습니다. 모든 bbox 축이 약 ±0.49 안에 있습니다. SUV 초안은 232,582 vertices로 상한에 가깝습니다. 이 초안이 최종 개선·선택으로 확정된 것은 아닙니다.

눈으로 확인한 대표 초안에서는 금빛 시계의 로마 숫자·시곗바늘·케이스, SUV의 타이어·루프랙·윈도·그릴, 축음기의 황동 나팔과 목재 상자, 호박의 골·줄기를 재현했습니다. 작은 글자, 형상 비율, 표면 무늬는 차이가 남습니다. 이는 정량적인 공식 승률 판정이 아닙니다.

## API 인증으로 중단된 부분

제공된 `/root/404-gen-key.txt`의 키로 최초 인증 확인과 실제 생성이 성공했습니다. 이후 OpenRouter가 `401 User not found`를 반환했고, 다시 확인했을 때 해당 파일도 존재하지 않았습니다. 네트워크 연결이 중간에 끊긴 요청도 1건 있었습니다. 모델 오류를 가짜 결과로 대체하지 않고 기록을 보존했습니다.

따라서 아래는 **아직 확인하지 못했습니다**.

- 실제 모델을 사용한 후보 선택→Astra 개선→최종 선택 전체 실행과 그 전체의 replay.
- 실제 라운드 3의 128개 이미지 결과와 공식 리더 대비 순승수 9개 이상.
- 운영 witness의 암호학적 증거와 공식 validator sandbox replay.
- 독립 source audit 승인, hotkey 등록/100-alpha lock/체인 commitment, 원격 GitHub 게시.

실제 응답을 사용한 호박 초안 단계의 replay는 검증했지만, 이것을 전체 생성기 replay 성공으로 부르지 않습니다. Python 단위 테스트의 전체 실행은 모의 witness를 사용했습니다. 조사 후 brief 분석의 reasoning effort는 medium으로 고정해 짧은 분석 호출의 출력 소진 위험을 줄였습니다. 보존된 실험 초안의 brief는 그 이전 개발 호출이므로 최종 소스의 모든 단계를 실측한 결과가 아닙니다.

## 개발 비용 기록

저장된 OpenRouter 응답 14개의 공급자 usage 비용 합계는 **$1.479594**입니다. 같은 14개 응답을 고정된 대회 tariff로 계산하면 **1,529,268 credits**입니다. 이 값은 4개 이미지에 나뉘어 사용한 합계이며 과제별 한도를 서로 보충하는 계산이 아닙니다. 별도의 짧은 연결 진단 호출과 응답을 받지 못한 요청의 청구 여부는 이 합계에 포함하지 않았습니다.

| 이미지 | 저장된 모델 응답 수 | 대회 credits | 응답의 OpenRouter 비용 합계 |
|---|---:|---:|---:|
| 시계 | 3 | 304,430 | $0.302371 |
| 축음기 | 2 | 224,354 | $0.218187 |
| 호박 | 7 | 766,690 | $0.730554 |
| SUV | 2 | 233,794 | $0.228482 |

실험에 사용한 키·인증 헤더는 Git 및 제출 패키지에 포함하지 않았습니다. `experiments/`는 개발 로그로 Git에서 제외합니다. 보존된 렌더·JS 초안은 `/root/404-round3-results/`에 있으며, **공식 라운드 3의 최종 선택 결과가 아닙니다**.

## 이어서 실행하기

1. 유효한 OpenRouter 키 파일 경로가 마련되면 `tools/develop.py`로 전체 개발 실행과 `--replay`를 확인합니다. 최종 소스로 만든 새 실험 디렉터리를 사용합니다.
2. 공개 전 확정한 소스를 본인 GitHub 저장소로 push하고, 전체 SHA를 chain commitment에 사용합니다.
3. 공식 생성은 OpenRouter가 아닌 OpenAI API 또는 Codex 구독으로 witness를 경유합니다. frozen prompts/seed와 승인된 SHA를 유지합니다.
4. 공식 이미지 128개가 공개되기 전에는 라운드 3 우승 여부를 증명할 수 없습니다. 완성된 생성기를 제출할 수 있는 것과 1등이 보장되는 것은 구분해야 합니다.
