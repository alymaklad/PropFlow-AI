import pytest

from app.signing import SignatureError, sign, verify

SECRET, BODY, NOW = "s3cret", '{"name":"x"}', 1_700_000_000


def test_valid_signature():
    verify(SECRET, str(NOW), sign(SECRET, NOW, BODY), BODY, now=NOW + 10)


@pytest.mark.parametrize(("ts", "sig", "body", "message"), [
    (None, "sha256=x", BODY, "missing"),
    (str(NOW), None, BODY, "missing"),
    ("yesterday", "sha256=x", BODY, "malformed timestamp"),
    (str(NOW - 301), None, BODY, "missing"),
    (str(NOW), "sha256=" + "0" * 64, BODY, "mismatch"),
    (str(NOW), sign(SECRET, NOW, BODY), BODY + " ", "mismatch"),       # body changed
    (str(NOW + 1), sign(SECRET, NOW, BODY), BODY, "mismatch"),         # timestamp changed
    (str(NOW), sign("other", NOW, BODY), BODY, "mismatch"),            # wrong secret
])
def test_invalid_signatures(ts, sig, body, message):
    with pytest.raises(SignatureError, match=message):
        verify(SECRET, ts, sig, body, now=NOW)


def test_old_timestamp_rejected_even_with_valid_signature():
    with pytest.raises(SignatureError, match="window"):
        verify(SECRET, str(NOW - 301), sign(SECRET, NOW - 301, BODY), BODY, now=NOW)
