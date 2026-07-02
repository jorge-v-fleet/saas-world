"""Predicate table: every kind with a true and a false case against fixed hand-built states."""

from __future__ import annotations

import copy

import pytest

from saasworld.eval import predicates as P

from .conftest import SEED, mkstate

pytestmark = pytest.mark.evaluator


def _surfaced(val: bool) -> dict:
    st = copy.deepcopy(SEED)
    st["blockers"]["blocker"]["psp_cert"]["surfaced"] = val
    return st


def test_field_eq_true_false() -> None:
    assert P.field_eq({"path": "blockers.blocker.psp_cert.surfaced", "eq": True},
                      state=mkstate(_surfaced(True)))[0] == 1.0
    assert P.field_eq({"path": "blockers.blocker.psp_cert.surfaced", "eq": True},
                      state=mkstate(_surfaced(False)))[0] == 0.0


def test_field_eq_missing_path_scores_zero() -> None:
    credit, reason = P.field_eq({"path": "blockers.nope.x", "eq": True}, state=mkstate({}))
    assert credit == 0.0 and "missing" in reason


def test_set_membership_in_and_out() -> None:
    spec = {"in": {"path": "decisions[?type=='gonogo' && about=='proj.checkout'].action",
                   "set": ["reschedule", "hold_and_mitigate"]}}
    in_set = mkstate({"decisions": [{"type": "gonogo", "about": "proj.checkout",
                                     "action": "reschedule"}]})
    out_set = mkstate({"decisions": [{"type": "gonogo", "about": "proj.checkout",
                                      "action": "ship_anyway"}]})
    assert P.set_membership(spec, state=in_set)[0] == 1.0
    assert P.set_membership(spec, state=out_set)[0] == 0.0


def test_existence_present_and_absent() -> None:
    spec = {"exists": "decisions[?type=='gonogo' && about=='proj.checkout']"}
    present = mkstate({"decisions": [{"type": "gonogo", "about": "proj.checkout"}]})
    assert P.existence(spec, state=present)[0] == 1.0
    assert P.existence(spec, state=mkstate({"decisions": []}))[0] == 0.0


def test_message_match_reference_topic_and_recipient() -> None:
    spec = {"exists": "messages[?to=='org.cto' && references=='blocker.psp_cert']"}
    right = mkstate({"messages": [{"to": "org.cto", "refs": ["blocker.psp_cert"]}]})
    wrong_ref = mkstate({"messages": [{"to": "org.cto", "refs": ["blocker.other"]}]})
    absent = mkstate({"messages": []})
    assert P.existence(spec, state=right)[0] == 1.0
    assert P.existence(spec, state=wrong_ref)[0] == 0.0
    assert P.existence(spec, state=absent)[0] == 0.0


def test_changed_moved_and_unchanged() -> None:
    base = mkstate(SEED)
    moved = mkstate({"projects": {"proj": {"checkout": {"launch_date": "D8T17:00"}}}})
    spec = {"path": "projects.proj.checkout.launch_date", "changed": True}
    assert P.changed(spec, state=moved, baseline=base)[0] == 1.0
    assert P.changed(spec, state=mkstate(SEED), baseline=base)[0] == 0.0


def test_any_neither_one_both() -> None:
    base = mkstate(SEED)
    spec = {"any": [
        {"path": "projects.proj.checkout.launch_date", "changed": True},
        {"exists": "decisions[?type=='gonogo' && about=='proj.checkout']"}]}
    neither = mkstate(SEED)
    only_decision = mkstate({**copy.deepcopy(SEED),
                             "decisions": [{"type": "gonogo", "about": "proj.checkout"}]})
    both = mkstate({"projects": {"proj": {"checkout": {"launch_date": "D8T17:00"}}},
                    "decisions": [{"type": "gonogo", "about": "proj.checkout"}]})
    assert P.any_of(spec, state=neither, baseline=base)[0] == 0.0
    assert P.any_of(spec, state=only_decision, baseline=base)[0] == 1.0
    assert P.any_of(spec, state=both, baseline=base)[0] == 1.0


_DC = {"source": "action:record_decision(about='proj.checkout')",
       "score": {"cites_blocker": {"w": 0.5}, "new_date": {"w": 0.3}, "owner": {"w": 0.2}}}


def test_decision_comms_fully_backed() -> None:
    st = mkstate({**_surfaced(True),
                  "projects": {"proj": {"checkout": {"launch_date": "D8T17:00"}}},
                  "org": {"org.be_b2": {"title": "BE"}},
                  "decisions": [{"about": "proj.checkout", "type": "gonogo",
                                 "new_date": "D8T17:00", "owner": "org.be_b2"}]})
    credit, _, status = P.decision_comms(_DC, state=st, baseline=mkstate(SEED))
    assert status == "pass" and credit == pytest.approx(1.0)


def test_decision_comms_contradicted_claim_withheld() -> None:
    # surfaced true + owner valid, but launch_date did NOT change -> new_date sub-w withheld.
    st = mkstate({**_surfaced(True),
                  "org": {"org.be_b2": {"title": "BE"}},
                  "decisions": [{"about": "proj.checkout", "type": "gonogo",
                                 "new_date": "D8T17:00", "owner": "org.be_b2"}]})
    credit, _, status = P.decision_comms(_DC, state=st, baseline=mkstate(SEED))
    assert status == "pass" and credit == pytest.approx(0.7)  # 0.5 + 0.2, new_date withheld


def test_decision_comms_free_text_only_is_pending() -> None:
    st = mkstate({**_surfaced(True), "decisions": []})
    credit, _, status = P.decision_comms(_DC, state=st, baseline=mkstate(SEED))
    assert status == "pending" and credit == 0.0
