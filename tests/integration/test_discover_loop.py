"""Discover a blocker end to end: load -> free-text message -> parse -> reveal + voiced reply.

Replay mode against the committed cassette: the parser maps the body to an intent, the UNCHANGED
decision core reveals (system-sourced), and the reply lands at the persona's response delay.
"""

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


def test_free_text_message_reveals_blocker_and_delivers_reply(client):
    _load(client)
    sent = _action(client, "send_message",
                   {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                    "refs": ["task.psp_integration"]})["result"]
    # Only the append fires now; npc_reply is scheduled for the persona's response delay.
    assert [(e["sim_time"], e["kind"]) for e in sent["events_since"]] == [(0, "send_message")]
    assert _get(client, PSP) is False  # reveal happens when Priya replies, not at send time

    res = _action(client, "wait", {"duration": 120})["result"]
    assert [(e["sim_time"], e["kind"]) for e in res["events_since"]] == [(90, "npc_reply")]
    assert _get(client, PSP) is True  # flipped by the decision core's reveal, system-sourced

    reply = _get(client, "messages")[-1]
    assert reply["from"] == "org.be_b2" and reply["to"] == "org.pm_a"
    assert reply["refs"] == ["blocker.psp_cert"] and "Mar 13" in reply["body"]


def test_message_to_non_npc_target_triggers_no_reaction(client):
    _load(client)
    _action(client, "send_message", {"to": "chan.checkout", "body": "Is the PSP ready for Friday?"})
    res = _action(client, "wait", {"duration": 120})["result"]
    assert res["events_since"] == []  # a channel is not a registered NPC -> plain append
    assert _get(client, PSP) is False


def test_wrong_topic_replies_but_does_not_reveal(client):
    _load(client)
    _action(client, "send_message",
            {"to": "org.be_b2", "body": "UI status?", "refs": ["task.checkout_ui"]})
    _action(client, "wait", {"duration": 120})
    assert _get(client, PSP) is False  # gate not satisfied
    assert _get(client, "messages")[-1]["kind"] == "ack"  # still acknowledged


def test_greeting_acknowledges_without_revealing(client):
    _load(client)
    _action(client, "send_message", {"to": "org.be_b2", "body": "hi"})
    _action(client, "wait", {"duration": 120})
    assert _get(client, PSP) is False
    assert _get(client, "messages")[-1]["kind"] == "ack"


def test_timeline_background_event_fires_during_advance(client):
    _load(client)
    res = _action(client, "wait", {"duration": 600})["result"]  # past D1T09:30 = 570
    kinds = [(e["sim_time"], e["kind"]) for e in res["events_since"]]
    assert (570, "meeting_start") in kinds  # scripted standup fired on its own
