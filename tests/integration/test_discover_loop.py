"""Discover-a-blocker end to end: load -> message Priya (intent) -> advance -> reply + reveal."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PSP = "blockers.blocker.psp_cert.surfaced"


def _rpc(client, method, params, id=1):
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": id, "method": method, "params": params})
    return r.json()


def _action(client, verb, args):
    return _rpc(client, "action", {"verb": verb, "args": args})


def _get(client, path):
    return _rpc(client, "get_state", {"path": path})["result"]


def _load(client):
    return _rpc(client, "load_scenario", {"name": "checkout-not-ready"})["result"]


def test_load_scenario_seeds_and_reports_version(client):
    res = _load(client)
    assert res["ok"] and res["scenario"] == "checkout-not-ready"
    assert res["dataset_version"].startswith("sha256:")
    assert _get(client, PSP) is False


def test_structured_intent_reveals_blocker_and_delivers_reply(client):
    _load(client)
    sent = _action(client, "send_message", {"to": "org.be_b2", "body": "PSP ready for Friday?",
                                             "intent": "ask_status",
                                             "refs": ["task.psp_integration"]})["result"]
    # npc_react fires synchronously within the zero-duration send; the reply is scheduled for later.
    assert [(e["sim_time"], e["kind"]) for e in sent["events_since"]] == [
        (0, "send_message"), (0, "npc_react")]
    assert _get(client, PSP) is True  # flipped by Priya's reveal (system-sourced), at send time

    res = _action(client, "wait", {"duration": 120})["result"]
    kinds = [(e["sim_time"], e["kind"]) for e in res["events_since"]]
    assert kinds == [(90, "deliver_reply")]  # reply lands at the modal response delay

    assert _get(client, PSP) is True
    inbox = _get(client, "messages")
    reply = inbox[-1]
    assert reply["from"] == "org.be_b2" and reply["to"] == "org.pm_a"
    assert reply["refs"] == ["blocker.psp_cert"]


def test_message_without_intent_triggers_no_reaction(client):
    _load(client)
    _action(client, "send_message", {"to": "org.be_b2", "body": "hi"})
    res = _action(client, "wait", {"duration": 120})["result"]
    assert res["events_since"] == []  # no npc_react without a structured intent
    assert _get(client, PSP) is False


def test_wrong_topic_replies_but_does_not_reveal(client):
    _load(client)
    _action(client, "send_message", {"to": "org.be_b2", "body": "UI status?",
                                      "intent": "ask_status", "refs": ["task.checkout_ui"]})
    _action(client, "wait", {"duration": 120})
    assert _get(client, PSP) is False  # gate not satisfied
    assert _get(client, "messages")[-1]["kind"] == "ack"  # still gets an acknowledgement


def test_timeline_background_event_fires_during_advance(client):
    _load(client)
    res = _action(client, "wait", {"duration": 600})["result"]  # past D1T09:30 = 570
    kinds = [(e["sim_time"], e["kind"]) for e in res["events_since"]]
    assert (570, "meeting_start") in kinds  # scripted standup fired on its own
