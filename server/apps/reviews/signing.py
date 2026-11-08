"""MaReSt v0.7.0 JWT construction on plain ``cryptography`` (design D2).

ES256 (ECDSA P-256 + SHA-256) with the JWS raw ``r‖s`` signature form —
no JOSE dependency (authlib's jose surface is partly typed and
deprecated; DER→raw conversion is ~10 lines here). The review signature
is derived locally: the upstream submit response returns none.
"""

import base64
import datetime
import json
import typing as t

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

#: MaReSt metadata keys Wodore accepts/enriches (validation allowlist).
METADATA_KEYS: tuple[str, ...] = (
    "nickname",
    "language",
    "experience_context",
    "is_personal_experience",
    "is_affiliated",
    "client_id",
    "license",
    "osm_id",
)


def _b64url(data: bytes) -> str:
    """base64url without padding (JWS)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _from_b64url(data: str) -> bytes:
    """base64url decode with padding restored."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def mint_keypair() -> tuple[str, dict[str, t.Any]]:
    """Mint an ES256 keypair.

    Returns:
        ``(kid, private_jwk)`` — kid is the whitespace-normalized
        single-line PEM (MaReSt), private_jwk the private JWK dict
        (``kty``, ``crv``, ``x``, ``y``, ``d``).
    """
    key = ec.generate_private_key(ec.SECP256R1())
    pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    kid = "".join(pem.splitlines())  # single line, marker spaces kept
    numbers = key.public_key().public_numbers()
    jwk: dict[str, t.Any] = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
        "d": _b64url(key.private_numbers().private_value.to_bytes(32, "big")),
    }
    return kid, jwk


def public_jwk(private_jwk: dict[str, t.Any]) -> dict[str, t.Any]:
    """The public verify JWK of a private JWK (MaReSt header form)."""
    return {
        "kty": private_jwk.get("kty", "EC"),
        "crv": private_jwk.get("crv", "P-256"),
        "x": private_jwk["x"],
        "y": private_jwk["y"],
        "key_ops": ["verify"],
        "ext": True,
    }


def _private_key(private_jwk: dict[str, t.Any]) -> ec.EllipticCurvePrivateKey:
    d_bytes = _from_b64url(str(private_jwk["d"]))
    d = int.from_bytes(d_bytes, "big")
    return ec.derive_private_key(d, ec.SECP256R1())


def _sign(private_jwk: dict[str, t.Any], signing_input: bytes) -> str:
    der = _private_key(private_jwk).sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _encode(obj: dict[str, t.Any]) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode())


def jwt_signature(jwt: str) -> str:
    """The derived review signature: the JWT's third segment."""
    return jwt.rsplit(".", maxsplit=1)[-1]


def build_jwt(
    kid: str,
    private_jwk: dict[str, t.Any],
    payload: dict[str, t.Any],
) -> str:
    """Sign one MaReSt JWT (header carries both ``kid`` PEM and ``jwk``)."""
    header = {
        "alg": "ES256",
        "typ": "JWT",
        "kid": kid,
        "jwk": json.dumps(public_jwk(private_jwk), separators=(",", ":")),
    }
    signing_input = f"{_encode(header)}.{_encode(payload)}".encode()
    return f"{signing_input.decode()}.{_sign(private_jwk, signing_input)}"


def build_review_jwt(
    kid: str,
    private_jwk: dict[str, t.Any],
    *,
    subject: str,
    rating: int | None,
    opinion: str | None,
    images: list[dict[str, t.Any]] | None,
    metadata: dict[str, t.Any],
    iat: datetime.datetime | None = None,
) -> str:
    """A rating/opinion review JWT (at least one of rating/opinion)."""
    payload: dict[str, t.Any] = {
        "iat": int(iat.timestamp()) if iat else _now_epoch(),
        "sub": subject,
        "metadata": metadata,
    }
    if rating is not None:
        payload["rating"] = rating
    if opinion is not None:
        payload["opinion"] = opinion
    if images:
        payload["images"] = images
    return build_jwt(kid, private_jwk, payload)


def build_action_jwt(
    kid: str,
    private_jwk: dict[str, t.Any],
    *,
    action: str,
    target_signature: str,
    rating: int | None = None,
    opinion: str | None = None,
) -> str:
    """An ``edit``/``delete``/``report_abuse`` JWT (``urn:maresi`` sub)."""
    payload: dict[str, t.Any] = {
        "iat": _now_epoch(),
        "sub": f"urn:maresi:{target_signature}",
        "action": action,
    }
    # report_abuse: reason as opinion, never a rating; edit: updates.
    if opinion is not None:
        payload["opinion"] = opinion
    if rating is not None and action == "edit":
        payload["rating"] = rating
    return build_jwt(kid, private_jwk, payload)


def _now_epoch() -> int:
    return int(datetime.datetime.now(tz=datetime.UTC).timestamp())


def verify_signature(jwt: str) -> bool:
    """Verify a JWT against its own embedded ``jwk``/``kid`` (tests)."""
    try:
        header_b64, payload_b64, signature = jwt.split(".")
        header = t.cast(dict[str, t.Any], json.loads(_from_b64url(header_b64)))
        jwk = t.cast(dict[str, t.Any], json.loads(str(header["jwk"])))
        x = int.from_bytes(_from_b64url(str(jwk["x"])), "big")
        y = int.from_bytes(_from_b64url(str(jwk["y"])), "big")
        public = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        raw = _from_b64url(signature)
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        public.verify(
            encode_dss_signature(r, s),
            f"{header_b64}.{payload_b64}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
        return True
    except Exception:
        return False
