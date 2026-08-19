##
# @file text.py
# @brief The two ways a report is written out: the terminal block and the Markdown
#        section. Both are built from the same findings, so they cannot drift.
#
# The shape is the same in both: tier, title, then the expected/found pair on its own
# lines. That pair IS the finding — a reader who wants to disagree can check the two
# numbers against the save without reading any of this code.


##
# @brief The summary line every report ends with, clean or not.
# @details It carries the rule count and the unimplemented list on purpose. A save that
# trips nothing has been checked against however many rules this game has, which is not
# the same as being clean, and hiding that would be the one dishonest thing this pass
# could do.
def _summary(report):
    n = len(report.findings)
    parts = [f"{n} finding{'' if n == 1 else 's'}.", f"Rules run: {report.rules_run}."]
    if report.unimplemented:
        parts.append(
            "Not implemented for this game: " + "; ".join(report.unimplemented) + "."
        )
    return " ".join(parts)


##
# @brief The terminal block, in the shape the CLI prints under `--validate`.
# @param report A @ref Report. @param label A slot label for the header, or None.
# @return A list of lines.
def validation_text(report, label=None):
    head = "VALIDATION" + (f" — {label}" if label else "")
    if report.no_rules:
        return [
            head,
            f"  No rules are implemented for {report.game}.",
            "  " + _summary(report),
        ]
    lines = [head]
    for f in report.findings:
        lines.append(f"  [{f.tier}] {f.title}")
        lines.append(f"    expected  {f.expected}")
        lines.append(f"    found     {f.found}")
        if f.note:
            lines.append(f"    note      {f.note}")
    lines.append("  " + _summary(report))
    return lines


##
# @brief The file-level block, for the terminal.
def validation_text_file(report):
    return validation_text(report, "file")


##
# @brief The file-level Markdown section. Its own heading level, because it is about
#        the container rather than about any one character in it.
def validation_md_file(report):
    lines = ["## Validation — file", ""]
    if not report.rules_run:
        return lines + [f"_No file-level rules apply here._ {_summary(report)}", ""]
    if not report.findings:
        lines.append("_Nothing contradictory found in the container._")
    for f in report.findings:
        lines.append(
            f"- **[{f.tier}] {f.title}** — expected {f.expected}; found {f.found}"
        )
        if f.note:
            lines.append(f"  - _{f.note}_")
    return lines + ["", f"_{_summary(report)}_", ""]


##
# @brief The Markdown section, one per character.
# @details Same findings, document formatting: the tier is bold because it is the thing
# a reader scans for, and the summary is italic because it is the caveat rather than the
# content.
# @param report A @ref Report. @return A list of Markdown lines.
def validation_md(report):
    lines = ["### Validation", ""]
    if report.no_rules:
        return lines + [
            f"_No rules are implemented for this game._ {_summary(report)}",
            "",
        ]
    if not report.findings:
        lines.append("_Nothing contradictory found._")
    for f in report.findings:
        lines.append(
            f"- **[{f.tier}] {f.title}** — expected {f.expected}; found {f.found}"
        )
        if f.note:
            lines.append(f"  - _{f.note}_")
    lines += ["", f"_{_summary(report)}_", ""]
    return lines
