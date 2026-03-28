"""Table formatting for eval results (txt and LaTeX)."""

from dataclasses import dataclass

from prettytable import PrettyTable, SINGLE_BORDER, TableStyle

from snc2fst.types import Segment, Word

_DASH = "---"


@dataclass
class TableData:
    """Processed results ready for rendering."""
    inputs: list[str]                    # original input strings, one per test
    rule_ids: list[str]                  # rule IDs in application order
    # rule_cells[i][j] = output string after rule i on test j, or None if unchanged
    rule_cells: list[list[str | None]]
    finals: list[str]                    # final surface form per test


def build_table(
    inputs: list[str],
    rule_ids: list[str],
    per_test_states: list[list[Word]],
    alphabet: dict[str, Segment],
) -> TableData:
    from snc2fst.alphabet import word_to_str

    rule_cells: list[list[str | None]] = []
    for i in range(len(rule_ids)):
        row: list[str | None] = []
        for states in per_test_states:
            before = states[i]
            after = states[i + 1]
            row.append(None if before == after else f"[{word_to_str(after, alphabet)}]")
        rule_cells.append(row)

    finals = [
        f"[{word_to_str(states[-1], alphabet)}]"
        for states in per_test_states
    ]

    return TableData(inputs=inputs, rule_ids=rule_ids, rule_cells=rule_cells, finals=finals)


# ---------------------------------------------------------------------------
# Text renderer (prettytable)
# ---------------------------------------------------------------------------

def format_txt(data: TableData) -> str:
    # Field names must be unique; use positional placeholders and hide the header.
    n_cols = 1 + len(data.inputs)
    fields = [f"_{j}" for j in range(n_cols)]

    table = PrettyTable(field_names=fields)
    table.set_style(TableStyle.DEFAULT)
    table.header = False

    table.align[fields[0]] = "r"
    for f in fields[1:]:
        table.align[f] = "c"

    ur_row = ["UR"] + [f"/{s}/" for s in data.inputs]
    table.add_row(ur_row, divider=True)

    for i, rule_id in enumerate(data.rule_ids):
        cells = [rule_id] + [c if c is not None else _DASH for c in data.rule_cells[i]]
        is_last_rule = i == len(data.rule_ids) - 1
        table.add_row(cells, divider=is_last_rule)

    table.add_row(["SR"] + data.finals)

    return table.get_string()


# ---------------------------------------------------------------------------
# LaTeX renderer
# ---------------------------------------------------------------------------

def format_latex(data: TableData) -> str:
    n_cols = 1 + len(data.inputs)
    col_spec = "r" + "c" * (n_cols - 1)

    def row_line(cells: list[str]) -> str:
        return "    " + " & ".join(cells) + " \\\\"

    lines = [f"  \\begin{{tabular}}{{{col_spec}}}"]
    lines.append(row_line(["UR"] + [f"/{s}/" for s in data.inputs]))
    lines.append("    \\hline")

    for i, rule_id in enumerate(data.rule_ids):
        cells = [f"${rule_id}$"] + [
            c if c is not None else _DASH for c in data.rule_cells[i]
        ]
        lines.append(row_line(cells))

    lines.append(row_line(["SR"] + data.finals))
    lines.append("  \\end{tabular}")

    return "\n".join(lines)
