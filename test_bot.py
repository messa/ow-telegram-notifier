from bot import redacted


def test_redacted():
    assert redacted('https://top:secret@example.com') == 'https://top:...@example.com'
