"""Content addressing: canonicalization + sha256 determinism + version stability."""

from __future__ import annotations

import json

import pytest

from saasworld.content_hash import (
    canonicalize,
    dataset_version,
    file_hash,
    hash_value,
    instance_hash,
    subtree_hash,
)

pytestmark = pytest.mark.content


def test_key_order_does_not_change_canonical_form():
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})


def test_whitespace_is_normalized():
    # Same content, different source formatting -> identical canonical form.
    a = json.loads('{"a":1, "b": [1,   2]}')
    b = json.loads('{"a":  1,"b":[1, 2]}')
    assert canonicalize(a) == canonicalize(b)


def test_annotation_fields_are_stripped():
    assert canonicalize({"a": 1, "_note": "ignore me"}) == canonicalize({"a": 1})
    assert hash_value({"a": 1, "_x": {"deep": 1}}) == hash_value({"a": 1})


def test_nested_annotations_stripped():
    assert canonicalize({"o": {"a": 1, "_c": 2}}) == canonicalize({"o": {"a": 1}})


def test_hash_is_deterministic():
    v = {"a": [1, 2, {"x": 1}], "b": "text"}
    assert hash_value(v) == hash_value(dict(v))


def test_changing_a_real_field_flips_the_hash():
    assert hash_value({"a": 1}) != hash_value({"a": 2})


def test_dataset_version_stable_across_reformatting():
    inst = {"seed": {"a": 1, "_note": "x"}, "timeline": {"at": "D1T09:30"}}
    reformatted = {"timeline": {"at": "D1T09:30"}, "seed": {"_note": "y", "a": 1}}
    assert dataset_version(inst) == dataset_version(reformatted)


def test_dataset_version_flips_on_real_change():
    a = {"seed": {"launch": "D5T17:00"}}
    b = {"seed": {"launch": "D6T17:00"}}
    assert dataset_version(a) != dataset_version(b)


def test_instance_hash_prefixed_and_stable():
    inst = {"seed": {"a": 1}}
    h = instance_hash(inst)
    assert h.startswith("sha256:")
    assert h == instance_hash({"seed": {"a": 1}})


def test_file_and_subtree_hash_ignore_formatting(tmp_path):
    (tmp_path / "one.json").write_text('{"a": 1,   "b": 2}')
    (tmp_path / "two.json").write_text('{"z": 3}')
    h1 = subtree_hash(tmp_path)

    (tmp_path / "one.json").write_text('{"b":2,"a":1}')  # reformatted, same content
    assert subtree_hash(tmp_path) == h1

    (tmp_path / "two.json").write_text('{"z": 4}')  # real change
    assert subtree_hash(tmp_path) != h1


def test_file_hash_matches_value_hash(tmp_path):
    p = tmp_path / "f.json"
    p.write_text('{"a":  1, "_note": "drop"}')
    assert file_hash(p) == hash_value({"a": 1})
