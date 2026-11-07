# 404 Round 3 procedural miner

이 작업 트리는 `improve/search-v3` 개선안입니다. 기존 등록 commit
`fff7a980eb4336f5f06e42e2f1e54c7dbbb932a2`와 별도로 검증하며,
이 개선안의 대회 등록·우승 여부를 뜻하지 않습니다.

라운드 공개 전 고정할 Python 생성기입니다. 입력 PNG 한 장을 받아, 검증·렌더를 거친 자급식 Three.js 모듈을 반환합니다. **우승이 입증된 제출물이라는 의미는 아닙니다.** 실제 라운드 3 이미지와 시드는 조사 시점에 공개되지 않았습니다.

엔트리포인트는 공식 async SDK 형식인 `async generate(image: bytes, seed: int, witness) -> str | None`입니다. 소스·데이터·프롬프트·요금표는 모두 이 저장소에 포함됩니다. 공식 대회 규정과 서비스 분석은 [분석 보고서](docs/ANALYSIS.ko.md)를 참고하세요.

게시 대상 저장소는 `https://github.com/Cr0wn0207/sn17-404-miner`입니다. 현재 작업 범위는 **로컬 검증과 패키지 준비**이며, 지갑 생성·등록·잠금·온체인 제출·GitHub push는 실행하지 않습니다. Codex 구독 설정과 로컬 점검 결과는 [구독 인증 안내](docs/SUBSCRIPTION.ko.md)에 있습니다.

지정 지갑은 `sn118-miner/default`이며 netuid 17 UID 100 등록을 확인했습니다. [등록·잠금·Witness 접근 점검](docs/REGISTRATION.ko.md)을 확인하세요. 준비된 `run-codex.sh`는 이 지갑과 Codex 구독을 선택하는 실행 도우미입니다.

## 생성 과정

1. Sol로 치수·재료·정체성을 결정하는 7개 특징을 분석합니다.
2. Sol 초안 최대 6개에서 서로 다른 형상 계보 3개를 남깁니다. 세 후보의 비율·실루엣을 병렬 개선한 뒤에도 서로 다른 계보 2개를 유지합니다.
3. 정면은 시점당 768, 회색 정면·측면은 384로 중립 조명 렌더합니다. 정면 4장의 물체 영역을 각각 확대해 작은 형상과 두께를 확인합니다. 확대 이미지는 모델 입력이며 출력 텍스처로 사용하지 않습니다.
4. 익명 AB/BA 평가로 후보를 비교합니다. 차이가 작거나 순서에 따라 판단이 뒤집히면 기존 후보를 보존합니다. 각 생존 후보의 수정 의견도 다음 단계에 전달합니다.
5. 예산이 허용하는 1~2개 후보에 Astra 개선을 적용하고, 두 계보를 Sol `xhigh`로 개선합니다. 최대 출력은 reasoning을 포함해 44,000 tokens입니다. 단계 전체의 보수적 비용을 호출 전에 예약합니다.
6. 선택 결과를 부모로 넘기는 `xhigh` 개선을 최대 두 번 더 수행합니다. 마지막으로 너비·높이 각각 ±12%의 실제 3D 비율 후보를 렌더·비교하고, 선택된 비율에서 ±15도 방향 후보를 비교합니다. 원본 대비 두 표시 순서의 유의미한 개선이 있어야 채택합니다. 최종 반환값은 실제 렌더했던 소스 그대로입니다.

비율 보정은 전체·주요 부품의 치수 비율을 먼저 기록하고 재작성에서 검토합니다.
정규화는 일반 메시의 월드 변환을 정점에 반영한 뒤 균등 배율로 맞춰,
회전한 부품의 큰 경계 상자 때문에 전체가 불필요하게 작아지는 문제를 줄입니다.
반사된 면의 winding, 투명 부품의 위치, instancing과 숨긴 부모의 가시성을 보존합니다.
비균등 비율 후보는 원본과 같은 시점·조명으로 검증하며, 개선 근거가 부족하면
원본을 유지합니다. 부품도 함께 변형되므로 바퀴의 원형·두께·반복 패턴과 측면
손상도 비교합니다. 방향 후보는 장식이나 내용물의 높이와 관계없이 실제로 회전합니다.

검증 거부는 후보당 1회만 고칩니다. 네트워크·증명·서비스 오류는 SDK의 동일 capture 복구에 맡깁니다. 실행 시각이나 호스트 파일을 보고 다른 경로를 선택하지 않습니다. 입력 이미지와 미리보기의 픽셀을 3D 텍스처로 옮기는 방식은 사용하지 않습니다.

## 공식 실행: Linux x86_64, Python 3.13

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install .
python -m pip check
cp witness.example.json witness.json
```

`witness.json`의 `proof_parameters`를 SDK 체크아웃의 `witness-server/verifier/params` 절대경로로 설정합니다. 이 경로의 공개 증명 파라미터 3개가 모두 있어야 합니다. 생성·재현에는 운영자가 제공하는 고정 환경을 사용하며, `generate` 안에서는 패키지를 설치하지 않습니다.

`codex_home`은 ChatGPT로 로그인한 계정의 `auth.json` 디렉터리, `codex`는 CLI 실행 경로입니다. 현재 환경의 설정은 `/root/.codex`와 `/root/.local/bin/codex`를 사용합니다. 다른 VPS 계정에서 실행하면 그 계정의 절대경로로 바꾸세요. 인증 토큰을 `witness.json`에 복사하지 않습니다.

지갑과 모델 호출 없이 로컬 설정을 확인합니다.

```bash
python tools/preflight.py
```

이 검사는 SDK 버전, CLI 로그인 상태, Witness의 구독 인증 로딩, native prover의 공개 파라미터 초기화를 확인합니다. 만료 임박 토큰의 자동 갱신이나 원격 gateway 세션·모델 생성은 실행하지 않습니다.

Finney netuid 17에 등록되고 100-alpha 잠금 요건을 충족한 hotkey, 읽을 수 있는 공개 GitHub 저장소와 전체 40자리 commit SHA가 필요합니다. **과제·시드 공개 전에 commit을 확정하고 체인 commitment의 `repo`, `commit`에 등록해야 합니다.** 공개 후 수정한 코드는 해당 라운드에 소급 제출할 수 없습니다.

공식 과제가 공개되면 해당 라운드의 `prompts.txt`와 정수 seed를 그대로 사용합니다.

```bash
python main.py --prompts /absolute/path/to/prompts.txt --seed PUBLISHED_SEED \
  --wallet-name YOUR_WALLET --wallet-hotkey YOUR_HOTKEY \
  --parallel-prompts 8 --parallel-calls 8
```

현재 선택한 인증은 **Codex 구독**입니다. 위 명령에 `--api`를 붙이지 않으면 배치 런타임이 `subscription="codex"`를 사용합니다. `witness.json`에 임의의 `subscription` 필드를 추가하는 방식은 아닙니다. 별도로 API 인증을 선택할 때만 `OPENAI_API_KEY`와 `--api`를 사용합니다. **OpenRouter 키는 공식 witness의 OpenAI 인증을 대신할 수 없습니다.** 배치 런타임이 최종 결과를 witness Pod에 제출하므로 지갑 등록과 사용자 확인 전에는 위 생성 명령을 실행하지 않습니다. 재시작할 때 같은 소스·seed·이미지·hotkey·인증 모드를 유지하세요.

## 로컬 개발·검증

```bash
python -m pytest -q
python main.py --help
python tools/develop.py --image /absolute/path/image.png --output experiments/example \
  --key-file /root/404-gen-key.txt
python tools/develop.py --image /absolute/path/image.png --output experiments/example --replay
```

기존 Codex 구독으로 로컬 실험과 캐시 재현을 실행할 수 있습니다.
이 경로는 직접 HTTPS와 로컬 렌더러를 쓰며 **Witness 증명이 없고 제출하지 않습니다.**

```bash
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt python tools/develop_codex.py \
  --image /absolute/path/image.png --output experiments/codex-example --seed 2312844523 \
  --witness-config /absolute/path/to/witness.json
python tools/develop_codex.py --image /absolute/path/image.png \
  --output experiments/codex-example --seed 2312844523 \
  --witness-config /absolute/path/to/witness.json --replay
```

개발 도구에는 `pytest`가 추가로 필요합니다. 공식 `render-service-js`를 `http://127.0.0.1:18040`에서 실행해야 합니다. OpenRouter 호출·렌더를 로컬에 기록해 같은 요청 순서와 출력 바이트를 검사합니다. 개발 도구는 `main.generate`에서 가져오지 않으며, **개발 로그는 공식 witness 증거가 아닙니다.** 비밀키와 실험 데이터는 Git에 포함하지 않습니다.

요금은 고정된 대회 tariff로 Decimal 정산합니다. reasoning과 cached input 전체가 포함됩니다. 출력 상한·입력 바이트·제한된 이미지 크기에 기반한 보수적 사전 견적과 100,000-credit 여유를 둡니다. 이미지 토큰 견적은 공급자 계약의 수학적 최대치 증명이 아니며, 실제 usage도 매 응답마다 검사합니다. 알 수 없는 usage로 실행을 계속하지 않습니다. 대회 한도는 과제당 5,000,000 credits, 60 calls입니다. 128개를 한도까지 쓰면 대회 환산 $640이며 실제 청구와는 다릅니다.

Python 테스트 통과, JavaScript validator 통과, 개발 로그 재실행 성공은 공식 sandbox replay·독립 source audit·라운드 우승과 각각 다릅니다. 실험 결과와 한계는 [검증 기록](docs/VALIDATION.ko.md)에 정리합니다.

## 출처

공식 규칙 요약과 tariff는 404-Repo/404-gen-subnet의 MIT 소스에서 가져왔습니다. [UPSTREAM_LICENSE](UPSTREAM_LICENSE)를 포함합니다. 구현은 이 과제를 위해 작성했으며, 이전 우승자의 소스는 경쟁 구조 분석에만 사용했습니다.
