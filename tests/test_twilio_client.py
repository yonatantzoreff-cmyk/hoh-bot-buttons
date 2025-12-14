import os
import pytest


os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")
os.environ.setdefault("TWILIO_MESSAGING_SERVICE_SID", "MGXXXX")

from app import twilio_client


def test_normalize_to_rejects_missing_number():
    with pytest.raises(ValueError):
        twilio_client._normalize_to("")

    with pytest.raises(ValueError):
        twilio_client._normalize_to("   ")
