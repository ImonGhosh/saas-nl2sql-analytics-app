import json
import os
from typing import Any, Dict


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def load_secrets() -> Dict[str, str]:
    secret_arn = os.getenv("SECRETS_MANAGER_ARN")
    if not secret_arn:
        return {}

    overwrite = _truthy(os.getenv("SECRETS_MANAGER_OVERWRITE"))
    region = (
        os.getenv("SECRETS_MANAGER_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )

    try:
        import boto3  # imported lazily to keep local dev lightweight
    except Exception as exc:
        raise RuntimeError(
            "SECRETS_MANAGER_ARN is set but boto3 is not available."
        ) from exc

    session = boto3.session.Session(region_name=region) if region else boto3.session.Session()
    client = session.client("secretsmanager")

    try:
        response = client.get_secret_value(SecretId=secret_arn)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load secrets from AWS Secrets Manager ({secret_arn})."
        ) from exc

    secret_string = response.get("SecretString")
    if not secret_string and response.get("SecretBinary") is not None:
        secret_binary = response.get("SecretBinary")
        if isinstance(secret_binary, (bytes, bytearray)):
            secret_string = secret_binary.decode("utf-8")
        else:
            secret_string = str(secret_binary)

    if not secret_string:
        raise RuntimeError("Secrets Manager response did not contain a secret payload.")

    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Secrets Manager secret is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Secrets Manager secret must be a JSON object.")

    applied: Dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        if overwrite or not os.getenv(key):
            os.environ[key] = value_str
            applied[key] = value_str

    return applied
