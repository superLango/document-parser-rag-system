from services.orchestration.idempotency import build_key

DOC = "doc-1"
SHA = "a" * 64


def _key(**overrides):
    values = {
        "prefix": "run",
        "document_id": DOC,
        "sha256": SHA,
        "channel": "stable",
        "parser_version": None,
    }
    values.update(overrides)
    return build_key(**values)


def test_same_inputs_produce_same_key() -> None:
    assert _key() == _key()


def test_channel_changes_key() -> None:
    assert _key() != _key(channel="candidate")


def test_parser_pin_changes_key() -> None:
    assert _key() != _key(parser_version="1.0.14")


def test_prefix_separates_create_and_reparse() -> None:
    assert _key() != _key(prefix="reparse")


def test_document_sha_changes_key() -> None:
    assert _key() != _key(sha256="b" * 64)


def test_key_is_sha256_hex() -> None:
    value = _key()
    assert len(value) == 64
    assert all(char in "0123456789abcdef" for char in value)
