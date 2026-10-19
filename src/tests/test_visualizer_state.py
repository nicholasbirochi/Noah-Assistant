import pytest

from visualizer import state


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(state, "_subscribers", [])
    monkeypatch.setattr(state, "_current", state.StateEvent(state="off"))
    monkeypatch.setattr(state, "_current_data", None)
    monkeypatch.setattr(state, "_current_presence", None)


def test_current_defaults_to_off():
    # "off", not "idle" -- idle specifically means the voice loop is
    # running and waiting for the wake word; before anything ever
    # publishes, Noah hasn't been turned on at all.
    assert state.current() == state.StateEvent(state="off")


def test_publish_updates_current():
    state.publish("listening")

    assert state.current() == state.StateEvent(state="listening", text="")


def test_publish_accepts_off():
    state.publish("listening")  # move away from the reset baseline first

    state.publish("off")

    assert state.current() == state.StateEvent(state="off", text="")


def test_publish_accepts_thinking():
    state.publish("thinking")

    assert state.current() == state.StateEvent(state="thinking", text="")


def test_publish_rejects_unknown_state():
    with pytest.raises(ValueError):
        state.publish("dancing")  # type: ignore[arg-type]


def test_subscriber_receives_published_events_in_order():
    q = state.subscribe()

    state.publish("listening")
    state.publish("speaking", text="olá")

    assert q.get_nowait() == state.StateEvent(state="listening", text="")
    assert q.get_nowait() == state.StateEvent(state="speaking", text="olá")


def test_unsubscribe_stops_delivery():
    q = state.subscribe()
    state.unsubscribe(q)

    state.publish("speaking", text="não deveria chegar")

    assert q.empty()


def test_unsubscribe_unknown_queue_is_a_safe_no_op():
    import queue

    state.unsubscribe(queue.Queue())  # never subscribed -- must not raise


def test_multiple_subscribers_each_get_their_own_copy():
    q1 = state.subscribe()
    q2 = state.subscribe()

    state.publish("listening")

    assert q1.get_nowait() == q2.get_nowait() == state.StateEvent(state="listening", text="")


def test_current_data_defaults_to_none():
    assert state.current_data() is None


def test_publish_data_updates_current_data():
    state.publish_data("finance", {"title": "Patrimônio", "bars": []})

    assert state.current_data() == state.DataEvent(kind="finance", payload={"title": "Patrimônio", "bars": []})


def test_clear_data_resets_current_data_to_none():
    state.publish_data("jobs", {"bars": []})

    state.clear_data()

    assert state.current_data() is None


def test_publish_data_is_independent_of_state_publish():
    # The real reason these are two separate channels: an unrelated
    # publish("listening") elsewhere in the codebase must never wipe out
    # whatever chart is currently on screen.
    state.publish_data("finance", {"bars": []})

    state.publish("listening")

    assert state.current_data() == state.DataEvent(kind="finance", payload={"bars": []})


def test_data_subscriber_receives_published_chart_events():
    q = state.subscribe()

    state.publish_data("jobs", {"bars": [{"label": "InfoJobs", "value": 5}]})

    assert q.get_nowait() == state.DataEvent(kind="jobs", payload={"bars": [{"label": "InfoJobs", "value": 5}]})


# ---- proactive presence card (assistant/presence.py) -- its own slot ----


def test_current_presence_defaults_to_none():
    assert state.current_presence() is None


def test_publish_presence_updates_current_presence_and_notifies():
    q = state.subscribe()
    payload = {"title": "Sugestões", "items": [{"source": "Lembretes", "why": "1 lembrete.", "action": "diga"}]}

    state.publish_presence(payload)

    expected = state.DataEvent(kind=state.PRESENCE_KIND, payload=payload)
    assert state.current_presence() == expected
    assert q.get_nowait() == expected


def test_clear_presence_resets_slot_and_sends_an_empty_item_list():
    # An empty item list (not an empty kind) -- an empty kind would be
    # read by the page as "clear the chart" instead.
    state.publish_presence({"items": [{"source": "x", "why": "y", "action": "z"}]})
    q = state.subscribe()

    state.clear_presence()

    assert state.current_presence() is None
    assert q.get_nowait() == state.DataEvent(kind=state.PRESENCE_KIND, payload={"items": []})


def test_presence_and_chart_slots_are_independent():
    state.publish_presence({"items": [{"source": "x", "why": "y", "action": "z"}]})
    state.publish_data("finance", {"bars": []})
    state.clear_data()
    state.publish("idle")

    assert state.current_presence() is not None

    state.publish_data("jobs", {"bars": []})
    state.clear_presence()

    assert state.current_data() == state.DataEvent(kind="jobs", payload={"bars": []})
