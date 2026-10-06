"""Audit of the prototype's legacy JSONL and JSON state files.

Read-only: it never writes to the files it inspects. It regenerates the
block between the GENERATED markers in docs/data_audit.md, so every number
in the audit comes from this script and the hand-written findings around
it are preserved.

Usage (from the repo root; `make audit` passes the local paths):
    python -m wallabot.importers.legacy_audit --out docs/data_audit.md \
        --jsonl current=data/wallapop_data.jsonl --state current=data ...
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

BEGIN = "<!-- BEGIN GENERATED: make audit -->"
END = "<!-- END GENERATED -->"

FIELDS = (
    "scanned_at",
    "search_term",
    "source",
    "item_id",
    "title",
    "price",
    "currency",
    "created_at",
    "url",
    "is_noise",
)


def source_of(row: dict) -> str:
    """Rows written before Vinted support have no source; they are Wallapop.

    Vinted ids carry the legacy "v:" prefix, which settles any ambiguity.
    """
    if str(row.get("item_id", "")).startswith("v:"):
        return "vinted"
    return row.get("source") or "wallapop"


@dataclass
class JsonlStats:
    label: str
    path: Path
    size_bytes: int = 0
    lines: int = 0
    bad_lines: int = 0
    schemas: Counter = field(default_factory=Counter)
    first_scan: str | None = None
    last_scan: str | None = None
    out_of_order: int = 0
    first_created: str | None = None
    last_created: str | None = None
    rows_by_source: Counter = field(default_factory=Counter)
    scan_range_by_source: dict[str, list[str]] = field(default_factory=dict)
    rows_by_term: Counter = field(default_factory=Counter)
    missing_or_null: Counter = field(default_factory=Counter)
    non_numeric_price: int = 0
    items_by_source: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    items_by_term: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    scans_by_term: dict[tuple[str, str], set] = field(default_factory=lambda: defaultdict(set))
    rows_per_item: Counter = field(default_factory=Counter)
    price_changes_per_item: Counter = field(default_factory=Counter)
    title_changes_per_item: Counter = field(default_factory=Counter)
    noise_flag_rows: int = 0
    noise_flag_disagree: int = 0
    # Last (search_term, noise under current rules) per item, to explain drops.
    last_term: dict[str, tuple[str, bool]] = field(default_factory=dict)

    @property
    def items(self) -> int:
        return len(self.rows_per_item)


def audit_jsonl(
    label: str, path: Path, is_noise: Callable[[str], bool] | None = None
) -> JsonlStats:
    """Stream one JSONL file and collect its statistics.

    Price and title changes are counted between consecutive observations of
    the same item in file order, which is scan order (out_of_order counts
    any line whose scanned_at goes backwards, to prove it).
    """
    stats = JsonlStats(label=label, path=path, size_bytes=path.stat().st_size)
    last_price: dict[str, object] = {}
    last_title: dict[str, object] = {}
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            stats.lines += 1
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                stats.bad_lines += 1
                continue
            if not isinstance(row, dict):
                stats.bad_lines += 1
                continue
            _observe(stats, row, last_price, last_title, is_noise)
    return stats


def _observe(stats, row, last_price, last_title, is_noise) -> None:
    stats.schemas[tuple(sorted(row))] += 1
    for name in FIELDS:
        if row.get(name) in (None, ""):
            stats.missing_or_null[name] += 1

    scanned = row.get("scanned_at")
    if scanned:
        if stats.last_scan and scanned < stats.last_scan:
            stats.out_of_order += 1
        stats.first_scan = min(filter(None, (stats.first_scan, scanned)))
        stats.last_scan = max(filter(None, (stats.last_scan, scanned)))
    created = row.get("created_at")
    if created:
        stats.first_created = min(filter(None, (stats.first_created, created)))
        stats.last_created = max(filter(None, (stats.last_created, created)))

    source = source_of(row)
    term = row.get("search_term") or ""
    item_id = row.get("item_id")
    price = row.get("price")
    stats.rows_by_source[source] += 1
    stats.rows_by_term[(source, term)] += 1
    if not isinstance(price, int | float) or isinstance(price, bool):
        stats.non_numeric_price += 1
    if scanned:
        stats.scans_by_term[(source, term)].add(scanned)
        span = stats.scan_range_by_source.setdefault(source, [scanned, scanned])
        span[0], span[1] = min(span[0], scanned), max(span[1], scanned)
    if item_id is None:
        return

    stats.items_by_source[source].add(item_id)
    stats.items_by_term[(source, term)].add(item_id)
    stats.rows_per_item[item_id] += 1
    if item_id in last_price and last_price[item_id] != price:
        stats.price_changes_per_item[item_id] += 1
    if item_id in last_title and last_title[item_id] != row.get("title"):
        stats.title_changes_per_item[item_id] += 1
    last_price[item_id] = price
    last_title[item_id] = row.get("title")

    noise_now = is_noise(row.get("title") or "") if is_noise is not None else False
    stats.last_term[item_id] = (term, noise_now)
    if is_noise is not None and "is_noise" in row:
        stats.noise_flag_rows += 1
        if bool(row["is_noise"]) != noise_now:
            stats.noise_flag_disagree += 1


@dataclass
class StateStats:
    label: str
    sizes: dict[str, int]
    seen: list[str] | None
    excluded: list[str] | None
    excluded_from_calc: list[str] | None
    reviewed: list[str] | None
    rules: list[dict] | None
    next_id: int | None


def _load_json(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def audit_state(label: str, directory: Path) -> StateStats:
    names = ["seen.json", "exclusions.json", "reviewed.json", "learned_filters.json"]
    sizes = {n: (directory / n).stat().st_size for n in names if (directory / n).exists()}
    seen = _load_json(directory / "seen.json")
    exclusions = _load_json(directory / "exclusions.json") or {}
    reviewed = _load_json(directory / "reviewed.json")
    learned = _load_json(directory / "learned_filters.json")
    return StateStats(
        label=label,
        sizes=sizes,
        seen=seen,
        excluded=exclusions.get("excluded") if exclusions else None,
        excluded_from_calc=exclusions.get("excludedFromCalc") if exclusions else None,
        reviewed=reviewed.get("reviewed") if reviewed else None,
        rules=learned.get("rules") if learned else None,
        next_id=learned.get("next_id") if learned else None,
    )


def load_legacy_watcher():
    """Import the prototype watcher from an empty directory.

    It reads seen.json and the JSONL from the working directory at import
    time; importing it from an empty folder keeps that from touching data.
    """
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as empty:
        os.chdir(empty)
        try:
            return importlib.import_module("wallabot.legacy.wallapop_watcher")
        finally:
            os.chdir(previous)


# ---------------------------------------------------------------- rendering


def _n(value: int) -> str:
    return f"{value:,}"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def _table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out + [""]


def render_jsonl_summary(all_stats: list[JsonlStats]) -> list[str]:
    rows = []
    for s in all_stats:
        rows.append(
            [
                f"`{s.label}`",
                _mb(s.size_bytes),
                _n(s.lines),
                _n(s.bad_lines),
                f"{s.first_scan} → {s.last_scan}",
                _n(s.rows_by_source["wallapop"]),
                _n(s.rows_by_source["vinted"]),
                _n(len(s.items_by_source["wallapop"])),
                _n(len(s.items_by_source["vinted"])),
                _n(s.out_of_order),
            ]
        )
    return _table(
        [
            "Dataset",
            "Size",
            "Lines",
            "Unparseable",
            "scanned_at range",
            "Wallapop rows",
            "Vinted rows",
            "Wallapop items",
            "Vinted items",
            "Out-of-order lines",
        ],
        rows,
    )


def render_jsonl_detail(s: JsonlStats) -> list[str]:
    out = [f"### `{s.label}` — `{s.path.name}`", ""]
    out.append(f"- `created_at` range: {s.first_created} → {s.last_created}")
    for source, (first, last) in sorted(s.scan_range_by_source.items()):
        out.append(f"- `scanned_at` range for {source}: {first} → {last}")
    schemas = ", ".join(
        f"{_n(count)} rows with {len(keys)} keys"
        + ("" if "source" in keys else " (no `source`)")
        + ("" if "is_noise" in keys else " (no `is_noise`)")
        for keys, count in s.schemas.most_common()
    )
    out.append(f"- Row schemas: {schemas}")
    per_item = list(s.rows_per_item.values())
    if per_item:
        out.append(
            f"- Rows per item: median {statistics.median(per_item):g}, max {_n(max(per_item))}"
        )
    changed = len(s.price_changes_per_item)
    out.append(
        f"- Items with at least one price change: {_n(changed)} of {_n(s.items)} "
        f"({_pct(changed, s.items)}); {_n(sum(s.price_changes_per_item.values()))} "
        "price changes in total"
    )
    retitled = len(s.title_changes_per_item)
    out.append(
        f"- Items with at least one title change: {_n(retitled)} ({_pct(retitled, s.items)})"
    )
    out.append(
        f"- Rows with a non-numeric price: {_n(s.non_numeric_price)} "
        f"({_pct(s.non_numeric_price, s.lines)})"
    )
    if s.noise_flag_rows:
        out.append(
            f"- Stored `is_noise` disagrees with the current rules on "
            f"{_n(s.noise_flag_disagree)} of {_n(s.noise_flag_rows)} rows "
            f"({_pct(s.noise_flag_disagree, s.noise_flag_rows)})"
        )
    out.append("")
    out.append("Missing or null rate per field:")
    out.append("")
    out += _table(
        ["Field", "Rows", "Rate"],
        [[f"`{f}`", _n(s.missing_or_null[f]), _pct(s.missing_or_null[f], s.lines)] for f in FIELDS],
    )
    out.append("Per search term (terms shown in quotes to expose whitespace):")
    out.append("")
    rows = []
    for source, term in sorted(s.rows_by_term):
        rows.append(
            [
                source,
                f'"{term}"',
                _n(s.rows_by_term[(source, term)]),
                _n(len(s.items_by_term[(source, term)])),
                _n(len(s.scans_by_term[(source, term)])),
            ]
        )
    out += _table(["Source", "Term", "Rows", "Unique items", "Distinct scanned_at values"], rows)
    return out


def render_overlap(all_stats: list[JsonlStats]) -> list[str]:
    rows = []
    for i, a in enumerate(all_stats):
        for b in all_stats[i + 1 :]:
            for source in ("wallapop", "vinted"):
                ia, ib = a.items_by_source[source], b.items_by_source[source]
                if not ia and not ib:
                    continue
                rows.append(
                    [
                        f"`{a.label}`",
                        f"`{b.label}`",
                        source,
                        _n(len(ia & ib)),
                        _n(len(ia - ib)),
                        _n(len(ib - ia)),
                    ]
                )
    return _table(["A", "B", "Source", "Items in both", "Only in A", "Only in B"], rows)


def render_dropped(all_stats: list[JsonlStats], chain: list[str]) -> list[str]:
    """Items present in one file of the chain and absent from the next.

    The chain lists files that should each contain the previous one (a
    backup followed by the file it was taken from), so any drop is data
    removed by hand rather than never collected.
    """
    by_label = {s.label: s for s in all_stats}
    labels = [label for label in chain if label in by_label]
    out = []
    for before, after in zip(labels, labels[1:], strict=False):
        a, b = by_label[before], by_label[after]
        dropped = [i for i in a.rows_per_item if i not in b.rows_per_item]
        by_term: Counter = Counter()
        clean_by_term: Counter = Counter()
        for item_id in dropped:
            term, noise_now = a.last_term[item_id]
            by_term[term] += 1
            clean_by_term[term] += not noise_now
        out.append(
            f"`{before}` → `{after}`: {_n(len(dropped))} items dropped, "
            f"{_n(sum(clean_by_term.values()))} of them not noise under the current rules."
        )
        out.append("")
        if dropped:
            rows = [
                [
                    f'"{t}"',
                    _n(n),
                    _n(clean_by_term[t]),
                    _n(len(a.items_by_term.get(("wallapop", t), ()))),
                ]
                for t, n in by_term.most_common()
            ]
            out += _table(
                ["Last search term", "Dropped items", "Not noise", "Items of that term before"],
                rows,
            )
    return out


def render_state(state: StateStats, jsonl_ids: set, searches: list[str]) -> list[str]:
    out = [f"### `{state.label}` state files", ""]
    out += _table(
        ["File", "Size"],
        [[f"`{name}`", f"{size / 1000:.1f} kB"] for name, size in state.sizes.items()],
    )
    facts = []
    if state.seen is not None:
        seen = set(state.seen)
        vinted = sum(1 for i in seen if str(i).startswith("v:"))
        facts.append(
            f"`seen.json`: {_n(len(seen))} ids ({_n(len(seen) - vinted)} Wallapop, "
            f"{_n(vinted)} Vinted); {_n(len(seen - jsonl_ids))} not in any audited JSONL"
        )
    excluded = set(state.excluded or [])
    if state.excluded is not None:
        facts.append(
            f"`exclusions.json`: {_n(len(excluded))} `excluded`, "
            f"{_n(len(state.excluded_from_calc or []))} `excludedFromCalc`; "
            f"{_n(len(excluded - jsonl_ids))} excluded ids not in any audited JSONL"
        )
    if state.reviewed is not None:
        reviewed = set(state.reviewed)
        facts.append(
            f"`reviewed.json`: {_n(len(reviewed))} ids; {_n(len(reviewed & excluded))} also "
            f"excluded; **{_n(len(reviewed - excluded))} reviewed but not excluded** "
            f"(the legacy label trap: import as `legacy_unknown`); "
            f"{_n(len(excluded - reviewed))} excluded but never reviewed"
        )
    if state.rules is not None:
        rules = state.rules
        exact = set(searches)
        stripped = {s.strip() for s in searches}
        dead = [r for r in rules if r.get("search_term") not in exact]
        dead_ws = [r for r in dead if r.get("search_term") in stripped]
        one_word = [r for r in rules if len(set(r.get("words") or [])) == 1]
        dup_words = [
            r for r in rules if len(r.get("words") or []) != len(set(r.get("words") or []))
        ]
        facts.append(
            f"`learned_filters.json`: {_n(len(rules))} rules (`next_id` {state.next_id}); "
            f"{_n(len(dead))} never fire in the watcher because their term is not an "
            f"exact current search term ({_n(len(dead_ws))} of them only differ by "
            f"whitespace); {_n(len(one_word))} have a single distinct word; "
            f"{_n(len(dup_words))} contain duplicated words"
        )
    out += [f"- {fact}" for fact in facts] + [""]
    return out


def render(
    all_stats: list[JsonlStats],
    detailed: set[str],
    states: list[StateStats],
    searches: list[str],
    chain: list[str] | None = None,
) -> str:
    jsonl_ids = set().union(*(set(s.rows_per_item) for s in all_stats)) if all_stats else set()
    out = [BEGIN, "", "## Generated tables", "", "### JSONL files", ""]
    out += render_jsonl_summary(all_stats)
    for s in all_stats:
        if s.label in detailed:
            out += render_jsonl_detail(s)
    out += ["### Overlap between JSONL files (unique item ids)", ""]
    out += render_overlap(all_stats)
    if chain:
        out += ["### Items removed between backups and the file they were taken from", ""]
        out += render_dropped(all_stats, chain)
    for state in states:
        out += render_state(state, jsonl_ids, searches)
    out.append(END)
    return "\n".join(out)


def write_generated_block(doc: Path, block: str) -> None:
    """Replace the generated block in doc, or append one if there is none."""
    text = doc.read_text(encoding="utf-8") if doc.exists() else ""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        text = head + block + tail
    else:
        text = text + ("\n" if text and not text.endswith("\n") else "") + block + "\n"
    doc.write_text(text, encoding="utf-8")


def _labelled(values: list[str]) -> list[tuple[str, Path]]:
    pairs = []
    for value in values:
        label, _, path = value.partition("=")
        pairs.append((label, Path(path)))
    return pairs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jsonl", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument(
        "--summary-only",
        action="append",
        default=[],
        metavar="LABEL",
        help="list this JSONL in the summary tables without a detail section",
    )
    parser.add_argument(
        "--chain",
        default="",
        metavar="LABEL,LABEL,...",
        help="JSONL labels in backup order; report items each step removed",
    )
    parser.add_argument("--state", action="append", default=[], metavar="LABEL=DIR")
    args = parser.parse_args(argv)

    watcher = load_legacy_watcher()
    all_stats = []
    for label, path in _labelled(args.jsonl):
        if not path.exists():
            print(f"skip {label}: {path} not found")
            continue
        print(f"auditing {label}: {path}")
        all_stats.append(audit_jsonl(label, path, watcher.is_noise))
    states = [audit_state(label, path) for label, path in _labelled(args.state) if path.is_dir()]
    detailed = {s.label for s in all_stats} - set(args.summary_only)
    write_generated_block(
        args.out,
        render(
            all_stats,
            detailed,
            states,
            list(watcher.SEARCHES),
            [c for c in args.chain.split(",") if c],
        ),
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
