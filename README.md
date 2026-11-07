# 404 procedural miner: V7 candidate

이 브랜치는 `improve/search-v7` 개발 후보입니다. 현재 Round 3에 등록된 소스는
`fff7a980eb4336f5f06e42e2f1e54c7dbbb932a2`이며, 이 브랜치로 교체되지 않습니다.
Round 3 과제·시드 공개 이후 작성한 개선은 해당 라운드에 소급 등록할 수 없습니다.
V7의 품질은 별도 고정 표본과 익명 비교로 검증하며 우승을 보장하지 않습니다.

## 생성 과정

V7은 전체 기준 사진과 물체 영역 확대본을 함께 모델에 제공합니다. 확대는 모델의 분석 입력이며 출력 텍스처에 복사하지 않습니다. 얇은 부품을 잘라 내지 않도록 기준 사진을 항상 유지합니다. 두 표시 순서에서 모든 측정 항목이 같거나 좋고, 정면 평균 0.1점 이상·식별 특징 추가·artifact 개선 중 하나가 일관되게 확인되면 작은 수정도 채택할 수 있습니다. 변경이 애매하거나 특정 항목이 나빠지면 기존의 큰 개선 기준을 적용합니다.


1. 기준 V3와 동일하게 7개 식별 특징·치수를 분석하고 독립 초안 최대 5개 (Terra xhigh 2개·Sol high 2개·Astra high 1개)에서 서로 다른 계보 3개를 남깁니다.
초안끼리의 첫 비교에서는 첫 번째 초안에 기존 우승자 보호 가중치를 주지 않습니다. 사진 속 측면·긴 축·기울기를 +Z 카메라에서 보이게 배치하며, 일반적인 정면 자세로 돌리지 않습니다.
2. 비율 개선에서 2개 계보를 유지하고 Astra 개선과 Sol xhigh 개선을 수행합니다.
3. 마지막 전체 재작성 하나를 국소 수정으로 바꿉니다. 사진과 네 방향 렌더를 본 별도 진단이 최대 3개 큰 오차와 구체적인 형상 수정을 지시합니다. 예산이 허용하면 Astra, 그렇지 않으면 Sol로 진단합니다.
4. Sol xhigh가 기존 소스의 정확한 문자열을 지정해 최대 8개 부분을 수정합니다. 원본에서 유일하지 않거나 서로 겹치는 편집은 거부합니다. 잘못된 코드·렌더·불명확한 비교에서는 기존 후보를 유지합니다.
5. 첫 국소 수정의 선택 결과를 다시 진단하고 최대 한 번 더 국소 수정합니다. 두 번째 편집은 32,768 토큰 상한과 최종 비교를 위한 500,000-credit 예약을 두며, 전체 단계가 예산에 맞지 않으면 건너뜁니다.
6. 너비·높이 ±12%, pitch ±15도 후보를 비교합니다. 이어 yaw ±15/30/90도 저해상도 렌더에서 형태가 개선된 최대 2개를 정밀 렌더하고 두 순서의 시각 평가를 통과해야 채택합니다. 픽셀 실루엣 점수만으로 출력물을 바꾸지 않습니다.
7. 실제 렌더·선택한 JavaScript 바이트를 그대로 반환합니다. 재현 경로는 소스·입력·시드·기록된 모델 응답·렌더에만 의존합니다.

사진과 렌더는 분석 입력입니다. 그 픽셀을 출력 텍스처에 복사하지 않습니다.
소스는 외부 파일·실험 결과·개발 캐시를 읽지 않습니다. 과제당 5,000,000 credits,
60 calls를 적용하며 단계 예약·실제 usage 정산을 모두 수행합니다.
최대 출력 토큰에는 reasoning이 포함됩니다. tariff credit은 실제 구독 청구액과 다릅니다.

## 실행

공식 엔트리포인트는 `async generate(image: bytes, seed: int, witness) -> str | None`입니다.
Linux x86_64 / Python 3.13에서 설치합니다.

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install .
cp witness.example.json witness.json
```

Codex 구독은 로그인된 CLI의 `codex_home`, `codex` 경로를 설정합니다.
인증 토큰을 소스나 witness.json에 복사하지 않습니다. 공개 증명 파라미터는
공식 SDK의 `witness-server/verifier/params` 디렉터리를 지정합니다.
[구독 인증 안내](docs/SUBSCRIPTION.ko.md), [공식 구조 분석](docs/ANALYSIS.ko.md)을 참고하세요.

새로 참가 가능한 라운드에서는 과제·시드 공개 전에 GitHub의 공개 repo/40자리
commit을 체인에 등록해야 합니다. 이후 해당 커밋으로만 실행합니다.

```bash
python main.py --prompts /absolute/path/prompts.txt --seed PUBLISHED_SEED \
  --wallet-name YOUR_WALLET --wallet-hotkey YOUR_HOTKEY \
  --parallel-prompts 4 --parallel-calls 4
```

위 명령은 공식 Witness에 결과를 저장합니다. `--api` 없이 Codex 구독을 사용합니다.
현재 Round 3 실행에는 기존 등록 작업 트리를 사용하며 V7 브랜치를 쓰지 않습니다.

## 로컬 검증

```bash
python -m pytest -q
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt python tools/develop_codex.py \
  --image /absolute/path/image.png --output experiments/example --seed 2312844523 \
  --witness-config /absolute/path/witness.json
python tools/develop_codex.py --image /absolute/path/image.png \
  --output experiments/example --seed 2312844523 \
  --witness-config /absolute/path/witness.json --replay
```

직접 Codex HTTPS·로컬 렌더를 사용하는 개발 실험은 Witness 증명이 없으며 제출하지 않습니다.
로컬 renderer는 공식 소스와 동일한 버전으로 127.0.0.1:18040에 실행해야 합니다.
캐시·인증·지갑·입력 사진·실험 결과는 Git에 포함하지 않습니다.
정확한 캐시 재현·JS validator 통과와 공식 sandbox replay·대회 승리는 별도입니다.

공식 규칙과 tariff는 MIT인 404-Repo/404-gen-subnet에서 가져왔으며
[UPSTREAM_LICENSE](UPSTREAM_LICENSE)를 포함합니다. 챔피언의 알고리즘과 결과는 비교·분석에 사용하며 그 소스 코드를 복제하지 않습니다.
