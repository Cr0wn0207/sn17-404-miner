"""Check local Codex subscription readiness without inference, wallet or chain writes.

No credentials, account identifiers or raw authentication errors are emitted.
An expiring token is reported locally, without attempting a refresh.
"""

import argparse
import base64
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class CheckFailed(Exception):
    """A nonsecret, actionable local check failure."""


def check_subscription(config):
    from witness_client.request import load_credentials

    auth_path = Path(config["codex_home"]).expanduser() / "auth.json"
    try:
        auth = json.loads(auth_path.read_text())
        if auth.get("auth_mode") != "chatgpt":
            raise CheckFailed("Codex file login is not ChatGPT subscription mode")
        tokens = auth["tokens"]
        payload = tokens["access_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if claims["exp"] <= time.time() + 300:
            raise CheckFailed("Codex token needs refresh; refresh the CLI login before generation")
        credential, account = load_credentials(config, "codex", None)
        if not credential or not account:
            raise CheckFailed("Witness could not load a subscription credential")
        # Do not return token-derived account data or the credential itself.
        del credential, account, tokens, auth, claims
        return {
            "mode": "codex",
            "file_login": True,
            "sdk_credentials_loaded": True,
            "refresh_attempted": False,
            "credential_values_emitted": False,
        }
    except CheckFailed:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise CheckFailed("Codex file credentials are missing or incompatible with the pinned SDK") from error


def check_cli(config):
    executable = config.get("codex", "codex")
    if not shutil.which(executable):
        raise CheckFailed("Codex executable is not available")
    result = subprocess.run(
        [executable, "login", "status"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "CODEX_HOME": config["codex_home"]},
        check=False,
    )
    authenticated = result.returncode == 0 and "Logged in using ChatGPT" in (result.stdout + result.stderr)
    if not authenticated:
        raise CheckFailed("Codex CLI does not report a ChatGPT login for the configured home")
    return {"chatgpt_login_reported": True, "raw_cli_output_recorded": False}


def check_parameters(config):
    from witness_client.proof import Prover

    directory = Path(config["proof_parameters"]).expanduser()
    names = ("circuit.bin", "proving.bin", "verifying.bin")
    if not all((directory / name).is_file() and (directory / name).stat().st_size > 0 for name in names):
        raise CheckFailed("One or more public proof parameter files are missing")
    prover = Prover(directory)
    return {
        "public_parameter_files": list(names),
        "native_prover_initialized": True,
        "verifying_key_sha256": prover.verifying_key_sha256,
    }


def check_versions():
    expected = {
        "404-witness-client": "0.2.17",
        "404-renderer-client": "0.1.4",
        "404-miner-runtime": "0.1.5",
        "pillow": "13.0.0",
        "openai": "3.29.0",
        "pydantic": "2.14.1",
    }
    installed = {name: importlib.metadata.version(name) for name in expected}
    if installed != expected or sys.version_info[:2] != (3, 13):
        raise CheckFailed("Python or SDK versions differ from the supported submission profile")
    return {"python": ".".join(map(str, sys.version_info[:3])), "packages": installed}


def run_checks(config_path):
    report = {
        "scope": "local_only",
        "authentication_mode": "codex",
        "checks": {},
        "not_performed": [
            "provider_inference",
            "witness_gateway_session",
            "wallet_creation",
            "hotkey_registration",
            "alpha_lock",
            "chain_commitment",
            "github_push",
        ],
    }
    config = json.loads(Path(config_path).read_text())
    if not config.get("codex_home") or not config.get("proof_parameters"):
        raise CheckFailed("witness.json must specify codex_home and proof_parameters")
    for name, operation in (
        ("versions", check_versions),
        ("codex_cli", lambda: check_cli(config)),
        ("subscription", lambda: check_subscription(config)),
        ("proof_parameters", lambda: check_parameters(config)),
    ):
        try:
            report["checks"][name] = {"passed": True, "detail": operation()}
        except (CheckFailed, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            # Only our own CheckFailed messages are safe to publish verbatim.
            detail = str(error) if isinstance(error, CheckFailed) else "Local check failed: " + type(error).__name__
            report["checks"][name] = {"passed": False, "detail": detail}
    report["passed"] = all(check["passed"] for check in report["checks"].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "witness.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_checks(args.config)
    except (OSError, ValueError, CheckFailed) as error:
        report = {"passed": False, "scope": "local_only", "error": type(error).__name__}
    result = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(result + "\n")
    print(result)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
