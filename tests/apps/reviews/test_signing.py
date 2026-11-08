"""Signing service tests: MaReSt compliance of generated JWTs."""

import base64
import json

import pytest

from server.apps.reviews import signing

pytestmark = pytest.mark.django_db


def _decode_segment(segment: str) -> dict[str, object]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class TestSigning:
    def test_minted_keypair_shape(self) -> None:
        kid, jwk = signing.mint_keypair()
        assert kid.startswith("-----BEGIN PUBLIC KEY-----")
        assert kid.endswith("-----END PUBLIC KEY-----")
        assert "\n" not in kid  # whitespace-normalized single line
        assert jwk["kty"] == "EC" and jwk["crv"] == "P-256"
        assert {"x", "y", "d"} <= set(jwk)

    def test_review_jwt_verifies_against_embedded_key(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_review_jwt(
            kid,
            jwk,
            subject="geo:0,0?q=Test&u=100",
            rating=75,
            opinion="great",
            images=[{"src": "https://files.mangrove.reviews/x.png", "label": "x"}],
            metadata={"nickname": "n", "client_id": "https://wodore.com"},
        )
        assert signing.verify_signature(jwt)
        assert signing.jwt_signature(jwt) == jwt.split(".")[2]

    def test_header_carries_kid_and_jwk(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_review_jwt(
            kid,
            jwk,
            subject="geo:0,0?q=T&u=10",
            rating=1,
            opinion=None,
            images=None,
            metadata={},
        )
        header = _decode_segment(jwt.split(".")[0])
        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"
        assert header["kid"] == kid
        inner = json.loads(str(header["jwk"]))
        assert inner["key_ops"] == ["verify"]
        assert inner["kty"] == "EC" and inner["crv"] == "P-256"

    def test_payload_has_required_claims(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_review_jwt(
            kid,
            jwk,
            subject="geo:0,0?q=T&u=10",
            rating=42,
            opinion=None,
            images=None,
            metadata={"client_id": "https://wodore.com"},
        )
        payload = _decode_segment(jwt.split(".")[1])
        assert payload["sub"] == "geo:0,0?q=T&u=10"
        assert payload["rating"] == 42
        assert "iat" in payload
        assert "opinion" not in payload  # unset optional fields absent

    def test_action_jwt_targets_maresi(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_action_jwt(
            kid,
            jwk,
            action="delete",
            target_signature="abc123",
        )
        payload = _decode_segment(jwt.split(".")[1])
        assert payload["sub"] == "urn:maresi:abc123"
        assert payload["action"] == "delete"
        assert signing.verify_signature(jwt)

    def test_edit_action_carries_rating_opinion(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_action_jwt(
            kid,
            jwk,
            action="edit",
            target_signature="abc",
            rating=80,
            opinion="updated",
        )
        payload = _decode_segment(jwt.split(".")[1])
        assert payload["rating"] == 80 and payload["opinion"] == "updated"

    def test_report_abuse_never_carries_rating(self) -> None:
        kid, jwk = signing.mint_keypair()
        jwt = signing.build_action_jwt(
            kid,
            jwk,
            action="report_abuse",
            target_signature="abc",
            opinion="spam",
            rating=99,  # rating must be ignored for reports
        )
        payload = _decode_segment(jwt.split(".")[1])
        assert "rating" not in payload
        assert payload["opinion"] == "spam"

    def test_flag_metadata_serialization_roundtrip(self) -> None:
        kid, jwk = signing.mint_keypair()
        metadata = {"is_personal_experience": True, "nickname": "x"}
        jwt = signing.build_review_jwt(
            kid,
            jwk,
            subject="geo:0,0?q=T&u=10",
            rating=10,
            opinion=None,
            images=None,
            metadata=metadata,
        )
        payload = _decode_segment(jwt.split(".")[1])
        assert payload["metadata"] == metadata
