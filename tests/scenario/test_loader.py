"""Scenario Loader: seed correctness, base⊕overlay merge, timeline scheduling, version guard."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saasworld.content_hash import dataset_version
from saasworld.kernel import Kernel
from saasworld.scenario.loader import ScenarioError, load, offset_to_minutes
from saasworld.state.store import WorldState

pytestmark = pytest.mark.scenario

SCENARIO = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "checkout-not-ready"


def _kernel() -> Kernel:
    return Kernel(WorldState())


def test_seed_populates_blocker_unsurfaced():
    k = _kernel()
    load(SCENARIO, k)
    assert k.state.read("blockers.blocker.psp_cert.surfaced") is False
    assert k.state.read("blockers.blocker.psp_cert.severity") == "launch_blocking"


def test_seed_populates_project_and_task():
    k = _kernel()
    load(SCENARIO, k)
    assert k.state.read("projects.proj.checkout.launch_date") == "D5T17:00"
    assert k.state.read("tasks.task.psp_integration.owner") == "org.be_b2"


def test_seed_channel_membership_for_send_precondition():
    k = _kernel()
    load(SCENARIO, k)
    # Channels are whole-key addressed, matching the send_message membership precondition.
    assert "org.pm_a" in k.state.snapshot()["chat"]["chan.checkout"]["members"]


def test_active_npc_config_merges_base_and_overlay():
    k = _kernel()
    loaded = load(SCENARIO, k)
    priya = loaded.engine.npcs["org.be_b2"]
    assert priya["identity"]["name"] == "Priya Nair"  # base
    assert "goals" in priya and priya["knowledge_scope"]  # overlay
    assert priya["knowledge_scope"][0]["links_blocker"] == "blocker.psp_cert"


def test_only_activated_npcs_are_registered():
    k = _kernel()
    loaded = load(SCENARIO, k)
    assert set(loaded.engine.npcs) == {"org.cto", "org.pm_b", "org.fe_a1", "org.be_b2"}


def test_timeline_entries_scheduled_into_kernel():
    k = _kernel()
    load(SCENARIO, k)
    assert len(k.queue) == 3  # three scripted entries
    fired = k.advance_until(offset_to_minutes("D1T09:30"))
    assert [e.kind for e in fired] == ["meeting_start"]


def test_offset_parsing():
    assert offset_to_minutes("D1T00:00") == 0
    assert offset_to_minutes("D1T09:30") == 570
    assert offset_to_minutes("D2T10:00") == 1440 + 600


def test_returns_dataset_version_and_eval_handle():
    k = _kernel()
    loaded = load(SCENARIO, k)
    assert loaded.dataset_version.startswith("sha256:")
    assert loaded.eval_ground_truth["checkpoints"]  # ground truth parked, but handed back


def _copy(tmp_path: Path) -> Path:
    dst = tmp_path / "checkout-not-ready"
    shutil.copytree(SCENARIO, dst)
    return dst


def _instance(root: Path) -> dict:
    return {
        "seed": json.loads((root / "seed.json").read_text()),
        "overlay": json.loads((root / "personas.overlay.json").read_text()),
        "timeline": json.loads((root / "timeline.json").read_text()),
        "eval": json.loads((root / "eval.json").read_text()),
    }


def test_matching_dataset_version_loads(tmp_path):
    root = _copy(tmp_path)
    manifest = json.loads((root / "scenario.json").read_text())
    manifest["dataset_version"] = dataset_version(_instance(root))
    (root / "scenario.json").write_text(json.dumps(manifest))
    loaded = load(root, _kernel())  # no raise
    assert loaded.dataset_version == manifest["dataset_version"]


def test_tampered_instance_is_refused(tmp_path):
    root = _copy(tmp_path)
    manifest = json.loads((root / "scenario.json").read_text())
    manifest["dataset_version"] = dataset_version(_instance(root))
    (root / "scenario.json").write_text(json.dumps(manifest))

    seed = json.loads((root / "seed.json").read_text())
    seed["projects"][0]["launch_date"] = "D6T17:00"  # tamper a real field
    (root / "seed.json").write_text(json.dumps(seed))

    with pytest.raises(ScenarioError):
        load(root, _kernel())
