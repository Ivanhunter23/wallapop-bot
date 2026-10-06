"""Tests for the legacy-file audit, on small synthetic files."""

import json

from wallabot.importers import legacy_audit as audit


def write_jsonl(path, rows, extra_lines=()):
    lines = [json.dumps(r) for r in rows] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def row(scanned, item_id, price, title="Pokemon Platino", term="pokemon platino", **extra):
    return {
        "scanned_at": scanned,
        "search_term": term,
        "item_id": item_id,
        "title": title,
        "price": price,
        "currency": "EUR",
        "created_at": None,
        "url": "u",
        **extra,
    }


def test_source_inference():
    assert audit.source_of({"item_id": "abc"}) == "wallapop"
    assert audit.source_of({"item_id": "v:1"}) == "vinted"
    assert audit.source_of({"item_id": "v:1", "source": "wallapop"}) == "vinted"
    assert audit.source_of({"item_id": "abc", "source": "vinted"}) == "vinted"


def test_counts_changes_between_consecutive_observations(tmp_path):
    path = tmp_path / "d.jsonl"
    write_jsonl(
        path,
        [
            row("2026-06-01T10:00:00", "a", 30.0),
            row("2026-06-01T10:00:00", "b", 10.0),
            row("2026-06-01T11:00:00", "a", 25.0),
            row("2026-06-01T12:00:00", "a", 30.0, title="Pokemon Platino DS"),
            row("2026-06-01T12:00:00", "v:9", "?", source="vinted"),
        ],
        extra_lines=['{"truncated'],
    )
    stats = audit.audit_jsonl("t", path, is_noise=lambda title: False)

    assert stats.lines == 6
    assert stats.bad_lines == 1
    assert stats.items == 3
    assert stats.price_changes_per_item == {"a": 2}
    assert stats.title_changes_per_item == {"a": 1}
    assert stats.rows_by_source == {"wallapop": 4, "vinted": 1}
    assert stats.non_numeric_price == 1
    assert stats.missing_or_null["created_at"] == 5
    assert stats.missing_or_null["source"] == 4
    assert (stats.first_scan, stats.last_scan) == ("2026-06-01T10:00:00", "2026-06-01T12:00:00")
    assert stats.out_of_order == 0


def test_flags_out_of_order_lines_and_noise_disagreement(tmp_path):
    path = tmp_path / "d.jsonl"
    write_jsonl(
        path,
        [
            row("2026-06-02T10:00:00", "a", 1.0, title="Funda DS", is_noise=False),
            row("2026-06-01T10:00:00", "b", 1.0, title="Pokemon", is_noise=False),
        ],
    )
    stats = audit.audit_jsonl("t", path, is_noise=lambda title: "Funda" in title)
    assert stats.out_of_order == 1
    assert (stats.noise_flag_rows, stats.noise_flag_disagree) == (2, 1)


def test_state_files_and_label_trap(tmp_path):
    (tmp_path / "seen.json").write_text(json.dumps(["a", "b", "v:1"]))
    (tmp_path / "exclusions.json").write_text(
        json.dumps({"excluded": ["a", "z"], "excludedFromCalc": []})
    )
    (tmp_path / "reviewed.json").write_text(json.dumps({"reviewed": ["a", "b", "c"]}))
    (tmp_path / "learned_filters.json").write_text(
        json.dumps(
            {
                "rules": [
                    {"search_term": "pokemon negro", "words": ["funda"]},
                    {"search_term": "pokemon negro ", "words": ["lote", "lote"]},
                    {"search_term": "pokemon negro ", "words": ["caja", "tcg"]},
                ],
                "next_id": 4,
            }
        )
    )
    state = audit.audit_state("s", tmp_path)
    text = "\n".join(audit.render_state(state, {"a", "b", "c"}, ["pokemon negro "]))

    assert "3 ids (2 Wallapop, 1 Vinted); 1 not in any audited JSONL" in text
    assert "1 also excluded; **2 reviewed but not excluded**" in text
    assert "1 excluded but never reviewed" in text
    assert "1 never fire in the watcher" in text
    assert "(1 of them only differ by whitespace)" in text
    assert "2 have a single distinct word" in text
    assert "1 contain duplicated words" in text


def test_dropped_items_between_chained_files(tmp_path):
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    write_jsonl(
        before,
        [
            row("t1", "a", 1.0, term="nintendo ds"),
            row("t1", "b", 1.0, term="nintendo ds", title="Funda DS"),
            row("t1", "c", 1.0),
        ],
    )
    write_jsonl(after, [row("t1", "c", 1.0)])

    def noise(title):
        return "Funda" in title

    stats = [audit.audit_jsonl("x", before, noise), audit.audit_jsonl("y", after, noise)]
    text = "\n".join(audit.render_dropped(stats, ["x", "y"]))
    assert "2 items dropped, 1 of them not noise" in text
    assert '| "nintendo ds" | 2 | 1 | 2 |' in text


def test_generated_block_replaces_only_between_markers(tmp_path):
    doc = tmp_path / "audit.md"
    doc.write_text(f"# Intro\n\n{audit.BEGIN}\nold\n{audit.END}\n\n## Findings\nkeep\n")
    audit.write_generated_block(doc, f"{audit.BEGIN}\nnew\n{audit.END}")
    assert doc.read_text() == f"# Intro\n\n{audit.BEGIN}\nnew\n{audit.END}\n\n## Findings\nkeep\n"


def test_generated_block_is_appended_when_missing(tmp_path):
    doc = tmp_path / "audit.md"
    audit.write_generated_block(doc, f"{audit.BEGIN}\nnew\n{audit.END}")
    assert doc.read_text() == f"{audit.BEGIN}\nnew\n{audit.END}\n"
