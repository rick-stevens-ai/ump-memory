import json
from ump_memory.cli import main


def test_cli_put_and_recall(tmp_path, capsys):
    store = tmp_path / "mem.jsonl"
    assert main(["--store", str(store), "put", "Kukla receives Sibline but notifier must run", "--tag", "sibline", "--id", "sibline_fix"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["id"] == "sibline_fix"
    assert main(["--store", str(store), "recall", "Sibline notifier", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["results"][0]["id"] == "sibline_fix"
