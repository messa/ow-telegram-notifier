from ow_telegram_notifier import redacted


def test_redacted():
    assert redacted('https://top:secret@example.com') == 'https://top:...@example.com'
