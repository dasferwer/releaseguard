import hashlib
import hmac

from releaseguard.main import settings, valid_signature


def test_webhook_signature() -> None:
    body = b'{"event_id":"evt-12345"}'
    digest = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    assert valid_signature(body, f"sha256={digest}")
    assert not valid_signature(body + b" ", f"sha256={digest}")
    assert not valid_signature(body, None)
