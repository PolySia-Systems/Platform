from polysia.security.secret_scan import scan_text


def test_secret_scan_detects_value_without_echoing_it() -> None:
    value = "0x" + ("0123456789abcdef" * 4)

    findings = scan_text(f"POLYMARKET_PRIVATE_KEY={value}", path="example.txt")

    assert [(finding.path, finding.rule) for finding in findings] == [
        ("example.txt", "private-key-assignment"),
        ("example.txt", "hex-private-key"),
    ]
    assert all(value not in repr(finding) for finding in findings)


def test_secret_scan_allows_empty_or_redacted_configuration() -> None:
    text = "POLYMARKET_PRIVATE_KEY=\nAPI_SECRET=redacted\nAPI_PASSPHRASE=none\n"

    assert scan_text(text, path=".env.example") == []
