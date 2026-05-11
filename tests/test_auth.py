"""Token generation + hashing round-trips."""

from ckg.auth import generate_token, hash_token, verify_token_hash


def test_token_shape():
    t = generate_token()
    assert t.startswith("ckg_")
    assert len(t) > 30


def test_token_hash_round_trip():
    t = generate_token()
    h = hash_token(t)
    assert verify_token_hash(h, t) is True
    assert verify_token_hash(h, t + "x") is False
