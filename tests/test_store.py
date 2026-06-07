from ump_memory import UMPStore, MemoryRecord


def test_put_get_recall(tmp_path):
    store = UMPStore(tmp_path / "mem.jsonl")
    rec = store.put(MemoryRecord(
        id="mem_policy_1",
        title="UMP not only source of truth",
        text="Use UMP for durable shared memories, but never only there. Keep file-backed memory and secure stores too.",
        kind="procedural",
        tags=["ump", "policy"],
        scope={"owner": "rick", "agent": "ollie", "visibility": "shared"},
        salience=0.9,
    ))
    assert store.get("mem_policy_1").text.startswith("Use UMP")
    hits = store.recall("UMP durable memory source of truth", scope={"owner": "rick", "visibility": "shared"})
    assert hits
    assert hits[0].record.id == rec.id
    assert hits[0].signals["scope_match"] > 0


def test_upsert_preserves_single_record(tmp_path):
    store = UMPStore(tmp_path / "mem.jsonl")
    store.put(MemoryRecord(id="x", text="first", kind="semantic"))
    store.put(MemoryRecord(id="x", text="second", kind="semantic"))
    records = store.list()
    assert len(records) == 1
    assert records[0].text == "second"


def test_filter_by_kind_and_tag(tmp_path):
    store = UMPStore(tmp_path / "mem.jsonl")
    store.put(MemoryRecord(id="a", text="Semantic Scholar key location pointer", kind="semantic", tags=["s2", "secret-pointer"]))
    store.put(MemoryRecord(id="b", text="Random unrelated note", kind="working", tags=["scratch"]))
    hits = store.recall("Semantic Scholar", filter={"tag": "secret-pointer", "kind": "semantic"})
    assert [h.record.id for h in hits] == ["a"]
