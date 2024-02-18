"""The tests for the notify smtp platform."""
from copy import deepcopy
from pathlib import Path
import re
from unittest.mock import patch

import pytest

import homeassistant.components.notify as notify
from homeassistant.components.smtp.const import DOMAIN
from homeassistant.components.smtp.notify import MailNotificationService
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .const import MOCKED_CONFIG_ENTRY_DATA

from tests.common import MockConfigEntry


class MockSMTP(MailNotificationService):
    """Test SMTP object that doesn't need a working server."""

    def _send_email(self, msg, recipients):
        """Just return msg string and recipients for testing."""
        return msg.as_string(), recipients


@pytest.fixture
def message():
    """Return MockSMTP object with test data."""
    mailer = MockSMTP(
        "localhost",
        25,
        5,
        "test@test.com",
        1,
        "testuser",
        "testpass",
        ["recip1@example.com", "testrecip@test.com"],
        "Home Assistant",
        0,
        True,
    )
    return mailer


HTML = """
        <!DOCTYPE html>
        <html lang="en" xmlns="http://www.w3.org/1999/xhtml">
            <head><meta charset="UTF-8"></head>
            <body>
              <div>
                <h1>Intruder alert at apartment!!</h1>
              </div>
              <div>
                <img alt="tests/testing_config/notify/test.jpg" src="cid:tests/testing_config/notify/test.jpg"/>
              </div>
            </body>
        </html>"""


EMAIL_DATA = [
    (
        "Test msg",
        {"images": ["tests/testing_config/notify/test.jpg"]},
        "Content-Type: multipart/mixed",
    ),
    (
        "Test msg",
        {"html": HTML, "images": ["tests/testing_config/notify/test.jpg"]},
        "Content-Type: multipart/related",
    ),
    (
        "Test msg",
        {"html": HTML, "images": ["tests/testing_config/notify/test_not_exists.jpg"]},
        "Content-Type: multipart/related",
    ),
    (
        "Test msg",
        {"html": HTML, "images": ["tests/testing_config/notify/test.pdf"]},
        "Content-Type: multipart/related",
    ),
]


@patch(
    "homeassistant.components.smtp.notify.MailNotificationService.connection_is_valid",
    lambda x: True,
)
async def test_reload_smtp(hass: HomeAssistant) -> None:
    """Verify we can reload a smtp config entry."""
    data = deepcopy(MOCKED_CONFIG_ENTRY_DATA)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    # Wait for discovery to finish
    await hass.async_block_till_done()

    assert hass.services.has_service(notify.DOMAIN, DOMAIN)
    await hass.config_entries.async_reload(entry.entry_id)
    assert not hass.services.has_service(notify.DOMAIN, DOMAIN)
    await hass.async_block_till_done()
    # Wait for discovery to finish
    assert hass.services.has_service(notify.DOMAIN, DOMAIN)

    # Unloading the entry should remove the service
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(notify.DOMAIN, DOMAIN)
    await hass.config_entries.async_setup(entry.entry_id)
    # Wait for discovery to finish
    await hass.async_block_till_done()
    assert hass.services.has_service(notify.DOMAIN, DOMAIN)


@pytest.mark.parametrize(
    ("message_data", "data", "content_type"),
    EMAIL_DATA,
    ids=[
        "Tests when sending text message and images.",
        "Tests when sending text message, HTML Template and images.",
        "Tests when image does not exist at mentioned location.",
        "Tests when image type cannot be detected or is of wrong type.",
    ],
)
def test_send_message(
    hass: HomeAssistant, message_data, data, content_type, message
) -> None:
    """Verify if we can send messages of all types correctly."""
    sample_email = "<mock@mock>"
    message.hass = hass
    hass.config.allowlist_external_dirs.add(Path("tests/testing_config").resolve())
    with patch("email.utils.make_msgid", return_value=sample_email):
        result, _ = message.send_message(message_data, data=data)
        assert content_type in result


@pytest.mark.parametrize(
    ("message_data", "data", "content_type"),
    [
        (
            "Test msg",
            {"images": ["tests/testing_config/notify/test.jpg"]},
            "Content-Type: multipart/mixed",
        ),
    ],
)
def test_sending_insecure_files_fails(
    hass: HomeAssistant,
    message_data,
    data,
    content_type,
    message,
) -> None:
    """Verify if we cannot send messages with insecure attachments."""
    sample_email = "<mock@mock>"
    message.hass = hass
    with patch("email.utils.make_msgid", return_value=sample_email), pytest.raises(
        ServiceValidationError
    ) as exc:
        result, _ = message.send_message(message_data, data=data)
        assert content_type in result
    assert exc.value.translation_key == "remote_path_not_allowed"
    assert exc.value.translation_domain == DOMAIN
    assert (
        str(exc.value.translation_placeholders["file_path"])
        == "tests/testing_config/notify"
    )
    assert exc.value.translation_placeholders["url"]
    assert exc.value.translation_placeholders["file_name"] == "test.jpg"


def test_send_text_message(hass: HomeAssistant, message) -> None:
    """Verify if we can send simple text message."""
    expected = (
        '^Content-Type: text/plain; charset="us-ascii"\n'
        "MIME-Version: 1.0\n"
        "Content-Transfer-Encoding: 7bit\n"
        "Subject: Home Assistant\n"
        "To: recip1@example.com,testrecip@test.com\n"
        "From: Home Assistant <test@test.com>\n"
        "X-Mailer: Home Assistant\n"
        "Date: [^\n]+\n"
        "Message-Id: <[^@]+@[^>]+>\n"
        "\n"
        "Test msg$"
    )
    sample_email = "<mock@mock>"
    message_data = "Test msg"
    with patch("email.utils.make_msgid", return_value=sample_email):
        result, _ = message.send_message(message_data)
        assert re.search(expected, result)


@pytest.mark.parametrize(
    "target",
    [
        None,
        "target@example.com",
    ],
    ids=[
        "Verify we can send email to default recipient.",
        "Verify email recipient can be overwritten by target arg.",
    ],
)
def test_send_target_message(target, hass: HomeAssistant, message) -> None:
    """Verify if we can send email to correct recipient."""
    sample_email = "<mock@mock>"
    message_data = "Test msg"
    with patch("email.utils.make_msgid", return_value=sample_email):
        if not target:
            expected_recipient = ["recip1@example.com", "testrecip@test.com"]
        else:
            expected_recipient = target

        _, recipient = message.send_message(message_data, target=target)
        assert recipient == expected_recipient
