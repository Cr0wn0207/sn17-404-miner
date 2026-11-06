# Codex 구독 인증 설정과 로컬 점검

사용자 지정 저장소: `https://github.com/Cr0wn0207/sn17-404-miner`.
현재 범위: 로컬 설정·검증·제출 패키지 준비. 원격 push와 온체인 작업은 실행하지 않습니다.

## 적용한 witness.json

```json
{
  "witness_url": "https://witness.subnet404.xyz",
  "proof_parameters": "/root/404-gen-subnet/witness-server/verifier/params",
  "codex_home": "/root/.codex",
  "codex": "/root/.local/bin/codex"
}
```

이 파일은 로컬에 생성하고 Git에서는 제외합니다. 패키지의 `local-config/witness.json`에도 같은 비밀정보 없는 경로 설정을 담습니다. 실제 토큰이나 계정 ID는 포함하지 않습니다. 다른 Ubuntu 계정에서 실행할 때에는 그 계정의 경로로 수정해야 합니다.

Codex는 파일 기반 인증에서 `CODEX_HOME/auth.json`을 사용하며 기본 디렉터리는 `~/.codex`입니다. Witness SDK는 해당 파일의 ChatGPT 구독 인증을 읽습니다. OS keyring에만 인증이 있으면 CLI 로그인 성공과 별개로 파일을 읽지 못할 수 있습니다. 현재 환경에서는 `/root/.codex/auth.json`이 존재하며 권한은 0600입니다. [공식 Codex 인증 문서](https://learn.chatgpt.com/docs/auth), [Witness SDK](https://github.com/404-Repo/404-gen-subnet/blob/3fbb72e6908ddab1c06bfb05a43f6c3ddf856cdb/witness-client/src/witness_client/auth.py).

## 실행 모드

현재 `main.py`는 공식 `miner_runtime.batch.run`을 사용합니다. `--api`를 생략하면 그 런타임이 `subscription="codex"`, `openai_api_key=None`을 전달합니다. 설정 JSON에 임의의 인증 모드 필드를 추가하지 않습니다.

```bash
/root/404-dev-venv/bin/python tools/preflight.py
```

이 명령은 지갑 없이 실행할 수 있습니다. 모델 추론, 토큰 갱신, gateway 세션 생성, 제출을 수행하지 않습니다. 만료가 5분 이내인 토큰은 갱신이 필요하다고 보고하고 멈춥니다. 일반 생성 중의 토큰 갱신은 SDK와 Codex CLI가 관리합니다.

## 확인 결과

- Codex CLI가 `Logged in using ChatGPT`를 보고했습니다.
- Witness SDK 0.2.17이 해당 파일에서 구독 인증을 읽고 형식을 검증했습니다.
- Python 3.13과 witness/renderer/runtime 등 pinned 버전이 일치했습니다.
- `circuit.bin`, `proving.bin`, `verifying.bin`으로 native prover가 초기화됐습니다.
- 인증 토큰·계정 ID는 로그, Git, 패키지에 포함하지 않았습니다.

자세한 비밀정보 없는 결과: [subscription-preflight.json](subscription-preflight.json).

이 결과는 로컬 로그인·SDK 호환성입니다. ChatGPT Pro의 실제 모델별 사용 가능량이나 원격 witness 접근 성공을 입증하는 것은 아닙니다. 후속 점검에서는 `sn118-miner/default`의 netuid 17 UID 100 등록을 확인했으나, gateway GET은 `403 hotkey_not_registered`를 반환했습니다. [등록 및 접근 점검](REGISTRATION.ko.md)에 현재 잠금량과 남은 조건을 정리했습니다.

## 사용자 확인 후의 실행 예시

wallet/hotkey 등록, 잠금, 소스 고정·공개, 공식 과제와 seed가 준비된 뒤에만 다음 명령을 실행합니다.

```bash
python main.py --prompts /absolute/path/to/prompts.txt --seed PUBLISHED_SEED \
  --wallet-name YOUR_WALLET --wallet-hotkey YOUR_HOTKEY \
  --parallel-prompts 8 --parallel-calls 8
```

`--api`는 붙이지 않습니다. 이 명령은 최종 결과를 Pod에 저장·제출하는 동작까지 포함합니다. 이번 로컬 점검에서는 실행하지 않았습니다.
