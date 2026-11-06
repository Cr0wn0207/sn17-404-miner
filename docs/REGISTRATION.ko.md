# 지갑 등록과 읽기 전용 준비 상태 확인

사용자 지정: wallet(coldkey 이름) `sn118-miner`, hotkey 이름 `default`, Finney netuid 17 UID `100`.

## 확인한 공개 온체인 상태

블록 `9449388`에서 확인했습니다.

- netuid 17의 hotkey→UID 조회 결과는 `100`입니다.
- UID 100→hotkey 역조회도 로컬 `default` hotkey 주소와 일치합니다.
- hotkey 소유 coldkey는 로컬 `sn118-miner`의 coldkey 공개 주소와 일치합니다.
- 해당 coldkey의 netuid 17 잠금량은 **0 alpha**입니다.

이후 확정 블록 `9449392`에서도 UID 100 및 coldkey 소유 관계를 확인했습니다. 이 확정 블록에서 해당 hotkey의 `Commitments.RevealedCommitments` 항목은 0건입니다. 등록 자체와 생성기 repo/commit의 대회 제출 commitment는 별개입니다.

원자료: [registration-check.json](registration-check.json). 기록은 해당 블록의 상태이며 후속 트랜잭션에 따라 달라질 수 있습니다.

대회 가이드의 요구 잠금량은 제출 hotkey당 100 alpha입니다. collector 기본 설정도 `required_lock_alpha=100.0`이며 동일 coldkey의 제출 hotkey 수를 곱해 확인합니다. 현재 0 alpha 조회 결과만으로는 이 조건을 충족하지 않습니다. 등록비 지불·스테이킹·alpha 잠금은 서로 다른 상태입니다. 이번 작업에서는 잠금이나 자금 이동을 실행하지 않았습니다.

근거: [공식 miner guide](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/miner-reference/README.md), [collector lock 검사](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/submission-collector/submission_collector/collection_iteration.py).

## Witness 상태 조회

공개 `/health` GET은 HTTP 200을 반환했습니다. 로컬 hotkey로 서명한 `GET /v1/pods/current`는 **HTTP 403, `hotkey_not_registered`**를 반환했습니다. 따라서 현재 gateway 접근은 확인되지 않았습니다. Pod 생성·모델 추론·결과 제출 요청은 하지 않았습니다.

공개 코드의 membership refresher는 확정 블록의 등록 목록을 읽고 600초 간격으로 갱신합니다. 온체인에서는 등록됐지만 gateway에서 아직 거부되는 현상은 snapshot 반영 지연일 가능성이 있습니다. 운영 서버의 실제 배포 상태·갱신 성공 여부를 직접 확인한 것은 아니므로 자동 해결을 보장하지 않습니다.

원자료: [gateway-readonly-check.json](gateway-readonly-check.json), [membership 갱신 코드](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/witness-gateway/pod_gateway/main.py).

## 준비된 실행 설정

패키지의 `run-codex.sh`는 다음 값을 지정합니다.

```text
wallet-name: sn118-miner
wallet-hotkey: default
wallet-path: /root/.bittensor/wallets
authentication: Codex subscription (--api 생략)
```

`./run-codex.sh --help`는 CLI 도움말만 확인합니다. 실제 과제와 seed를 전달하면 SDK batch가 생성과 최종 저장·제출까지 수행하므로, 사용자 진행 확인과 남은 조건을 갖춘 후 실행해야 합니다. 이번 작업에서는 생성 실행을 하지 않았습니다.

다른 VPS 계정으로 옮기는 경우 Python 환경·wallet 경로와 `witness.json`의 경로를 수정해야 합니다. 지갑 비밀키와 Codex 인증 파일은 패키지에 포함하지 않습니다.

## 남은 조건

1. 제출 hotkey에 필요한 netuid 17 alpha 잠금 요건 확인.
2. gateway가 해당 등록 hotkey를 받아들이는지 다시 확인.
3. 사용자 확인 후 공개 저장소 게시와 정확한 repo/commit commitment 준비·제출.
4. 공식 과제·seed와 Codex 인증으로 실제 생성·replay·소스 감사 확인.

GitHub `ls-remote` 조회는 성공했으나 HEAD/main ref가 없었습니다. 조회 시점에는 지정 저장소에 해당 브랜치가 게시되지 않은 상태입니다. 원격 push와 온체인 작업은 수행하지 않았습니다.
