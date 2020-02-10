from ow_telegram_notifier import redacted, generate_message_texts


def test_redacted():
    assert redacted('https://top:secret@example.com') == 'https://top:...@example.com'

def test_generate_message_texts_empty():
    message_texts, _ = generate_message_texts([], [], None)
    assert message_texts == []


def test_generate_message_texts_short_lived_watchdog_alert():
    alert = {
        "id": "QWxlcnQ6aHJlMnBiMGY=",
        "alertId": "hre2pb0f",
        "alertType": "watchdog",
        "streamId": "3scxxinu",
        "stream": {"labelJSON": '{"agent":"system","host":"example.com"}'},
        "itemPath": ["watchdog"],
        "lastItemUnit": None,
        "lastItemValueJSON": None,
    }
    notify_aux = None
    message_texts, notify_aux = generate_message_texts([], [alert], notify_aux, now=10)
    assert message_texts == []
    message_texts, notify_aux = generate_message_texts([alert], [alert], notify_aux, now=20)
    assert message_texts == []
    message_texts, notify_aux = generate_message_texts([alert], [], notify_aux, now=30)
    assert message_texts == [r'♻️ agent\=`system` host\=`example\.com` *watchdog* watchdog \- \(`hre2pb0f`\)']
    message_texts, notify_aux = generate_message_texts([], [], notify_aux, now=10)
    assert message_texts == []



def test_generate_message_texts_long_lived_watchdog_alert():
    alert = {
        "id": "QWxlcnQ6aHJlMnBiMGY=",
        "alertId": "hre2pb0f",
        "alertType": "watchdog",
        "streamId": "3scxxinu",
        "stream": {"labelJSON": '{"agent":"system","host":"example.com"}'},
        "itemPath": ["watchdog"],
        "lastItemUnit": None,
        "lastItemValueJSON": None,
    }
    notify_aux = None
    message_texts, notify_aux = generate_message_texts([], [alert], notify_aux, now=10)
    assert message_texts == []
    message_texts, notify_aux = generate_message_texts([alert], [alert], notify_aux, now=20)
    assert message_texts == []
    message_texts, notify_aux = generate_message_texts([alert], [alert], notify_aux, now=1010)
    assert message_texts == [r'🔥 agent\=`system` host\=`example\.com` *watchdog* watchdog \- \(`hre2pb0f`\)']
    message_texts, notify_aux = generate_message_texts([alert], [], notify_aux, now=1010)
    assert message_texts == [r'🌴 agent\=`system` host\=`example\.com` *watchdog* watchdog \- \(`hre2pb0f`\)']
    message_texts, notify_aux = generate_message_texts([], [], notify_aux, now=10)
    assert message_texts == []
