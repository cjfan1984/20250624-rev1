from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DATA_AAD = b"SKU-PWA-HYBRID-DATA-V1"
PART_NAMES = (
    "full-envelope.part01",
    "full-envelope.part02",
    "full-envelope.part03",
    "full-envelope.part04a",
    "full-envelope.part04b",
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_b64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise SystemExit(f"{field} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise SystemExit(f"{field} is invalid base64") from exc


def load_public_key(keyring_path: Path) -> tuple[rsa.RSAPublicKey, str]:
    keyring = json.loads(keyring_path.read_text(encoding="utf-8"))
    if keyring.get("version") != 1 or keyring.get("kind") != "SKU-PWA-HYBRID-KEYRING":
        raise SystemExit("unsupported keyring")
    public_info = keyring.get("publicKey")
    if not isinstance(public_info, dict):
        raise SystemExit("public key metadata missing")
    public_der = decode_b64(public_info.get("data"), "publicKey.data")
    fingerprint = hashlib.sha256(public_der).hexdigest()
    if fingerprint != public_info.get("fingerprintSha256"):
        raise SystemExit("public key fingerprint mismatch")
    public_key = serialization.load_der_public_key(public_der)
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size != 3_072:
        raise SystemExit("expected an RSA-3072 public key")
    return public_key, fingerprint


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt a PWA JSON payload using only the hybrid public key."
    )
    parser.add_argument("--input", type=Path, default=Path("new-pwa-data.json"))
    parser.add_argument("--keyring", type=Path, default=Path("hybrid-keyring.json"))
    parser.add_argument("--output", type=Path, default=Path("hybrid-envelope.json"))
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        help="Also split the compact envelope into the five production fragment names.",
    )
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit("input must be a non-empty JSON array")
    ranks = [int(row["rank"]) for row in data]
    if len(ranks) != len(set(ranks)):
        raise SystemExit("rank values must be unique")
    required_fields = {
        "rank",
        "sku",
        "stage",
        "pwaTier",
        "profitKnown",
        "profitRankEligible",
    }
    for index, row in enumerate(data):
        if not isinstance(row, dict) or not required_fields.issubset(row):
            raise SystemExit(f"row {index} is missing required PWA contract fields")
        if not isinstance(row["profitKnown"], bool) or not isinstance(
            row["profitRankEligible"], bool
        ):
            raise SystemExit(f"row {index} eligibility flags must be booleans")
        if row["stage"] == "STOP" or row["pwaTier"] in {
            "STOP_AUDIT",
            "CANDIDATE_PENDING",
        }:
            if row["profitRankEligible"]:
                raise SystemExit(f"row {index} is ineligible but marked for profit ranking")
        if row["profitRankEligible"] and (
            not row["profitKnown"]
            or not isinstance(row.get("profit"), (int, float))
            or not isinstance(row.get("margin"), (int, float))
        ):
            raise SystemExit(f"row {index} lacks a closed profit chain")
        for value_field, known_field in (
            ("price", "priceKnown"),
            ("cost", "costKnown"),
            ("weight", "weightKnown"),
            ("profit", "profitKnown"),
            ("margin", "profitKnown"),
        ):
            if row.get(known_field) is False and row.get(value_field) is not None:
                raise SystemExit(
                    f"row {index} stores {value_field} despite {known_field}=false"
                )

    public_key, fingerprint = load_public_key(args.keyring)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(plain, compresslevel=9, mtime=0)
    data_key = os.urandom(32)
    iv = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(iv, packed, DATA_AAD)
    wrapped_key = public_key.encrypt(
        data_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    del data_key

    envelope = {
        "version": 1,
        "kind": "SKU-PWA-HYBRID-ENVELOPE",
        "records": len(data),
        "payloadSchema": "SKU-PRODUCT-CARD-V3",
        "compression": "gzip",
        "contentType": "application/json; charset=utf-8",
        "dataEncryption": {
            "algorithm": "AES-256-GCM",
            "iv": b64(iv),
            "aad": DATA_AAD.decode("ascii"),
            "ciphertext": b64(ciphertext),
        },
        "keyWrapping": {
            "algorithm": "RSA-OAEP-3072-SHA256",
            "wrappedKey": b64(wrapped_key),
            "publicKeyFingerprintSha256": fingerprint,
        },
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    args.output.write_text(encoded, encoding="utf-8")
    fragment_sizes: list[int] | None = None
    if args.fragments_dir is not None:
        args.fragments_dir.mkdir(parents=True, exist_ok=True)
        base, extra = divmod(len(encoded), len(PART_NAMES))
        offset = 0
        fragment_sizes = []
        for index, name in enumerate(PART_NAMES):
            size = base + (1 if index < extra else 0)
            fragment = encoded[offset : offset + size]
            (args.fragments_dir / name).write_text(fragment, encoding="utf-8")
            fragment_sizes.append(len(fragment.encode("utf-8")))
            offset += size
        reassembled = "".join(
            (args.fragments_dir / name).read_text(encoding="utf-8") for name in PART_NAMES
        )
        if reassembled != encoded:
            raise SystemExit("fragment reassembly mismatch")
    print(
        json.dumps(
            {
                "output": args.output.name,
                "rows": len(data),
                "uniqueRanks": len(set(ranks)),
                "plainBytes": len(plain),
                "gzipBytes": len(packed),
                "envelopeBytes": len(encoded.encode("utf-8")),
                "envelopeSha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                "publicKeyFingerprintSha256": fingerprint,
                "fragmentBytes": fragment_sizes,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
