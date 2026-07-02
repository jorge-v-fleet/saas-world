"""Path reader: dotted read, ['index'], and [?a==X && b==Y] filter with refs/references aliasing."""

from __future__ import annotations

import pytest

from saasworld.eval.paths import MISSING, read

from .conftest import mkstate

pytestmark = pytest.mark.evaluator


def test_dotted_scalar_read() -> None:
    st = mkstate({"blockers": {"blocker": {"psp_cert": {"surfaced": True}}}})
    assert read(st, "blockers.blocker.psp_cert.surfaced") is True


def test_missing_path_reads_missing_not_crash() -> None:
    st = mkstate({"projects": {}})
    assert read(st, "projects.proj.checkout.launch_date") is MISSING


def test_dict_index_form() -> None:
    st = mkstate({"projects": {"proj.checkout": {"owner": "org.pm_a"}}})
    assert read(st, "projects['proj.checkout'].owner") == "org.pm_a"


def test_filter_returns_matching_list() -> None:
    st = mkstate({"decisions": [
        {"type": "gonogo", "about": "proj.checkout", "action": "reschedule"},
        {"type": "note", "about": "proj.checkout"}]})
    got = read(st, "decisions[?type=='gonogo' && about=='proj.checkout']")
    assert isinstance(got, list) and len(got) == 1


def test_filter_projection_and_empty() -> None:
    st = mkstate({"decisions": [{"type": "gonogo", "about": "proj.checkout", "action": "hold"}]})
    assert read(st, "decisions[?type=='gonogo' && about=='proj.checkout'].action") == ["hold"]
    assert read(st, "decisions[?type=='gonogo' && about=='other']") == []


def test_references_aliases_refs_list_membership() -> None:
    st = mkstate({"messages": [{"to": "org.cto", "refs": ["blocker.psp_cert"]}]})
    assert read(st, "messages[?to=='org.cto' && references=='blocker.psp_cert']")
    assert read(st, "messages[?to=='org.cto' && references=='other']") == []
