"""Renders a dispute report into an insurance-ready PDF incident docket (reportlab, no external assets)."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

STY = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=STY["Title"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("H2", parent=STY["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0f3d3e"))
BODY = ParagraphStyle("Body", parent=STY["BodyText"], fontSize=9.5, leading=13)
SMALL = ParagraphStyle("Small", parent=STY["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#555555"))


def _table(data, widths=None, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3d3e")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def render_docket_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"ColdTrace Incident Docket #{report['dispute_id']}")
    E = []
    E.append(Paragraph("ColdTrace &mdash; Cold-Chain Incident Docket", H1))
    E.append(Paragraph(f"Dispute #{report['dispute_id']} &middot; Shipment ref {report['shipment_id']} &middot; "
                       f"Generated {report['generated_at']} &middot; Contract {report['contract_id']}", SMALL))
    E.append(Spacer(1, 6))
    E.append(Paragraph("This docket is generated automatically from tamper-evident sensor records and a contractual "
                       "liability model; see Methodology for details.", SMALL))

    E.append(Paragraph("Parties", H2))
    E.append(_table([["Role", "Party"], ["Claimant", report.get("claimant") or "-"], ["Respondent", report.get("respondent") or "-"]],
                    widths=[40 * mm, 120 * mm]))

    E.append(Paragraph("Executive summary", H2))
    E.append(Paragraph(report["summary"], BODY))
    E.append(Paragraph(f"<b>Recommendation:</b> {report['recommendation']}", BODY))

    t = report["totals"]
    E.append(Paragraph("Loss assessment", H2))
    E.append(_table([
        ["Metric", "Value"],
        ["Assessed loss", f"{t['loss_pct']:.2f}% of declared value"],
        ["Declared cargo value", f"INR {t['declared_value_inr']:,.0f}"],
        ["Value at risk", f"INR {t['loss_inr']:,.0f}"],
        ["Minutes outside allowed band", f"{t['minutes_out_of_band']:.0f}"],
        ["Peak temperature", f"{t['max_temp_c']} C" if t["max_temp_c"] is not None else "-"],
        ["First breach", t["first_breach_ts"] or "None recorded"],
    ], widths=[70 * mm, 90 * mm]))

    E.append(Paragraph("Evidence integrity", H2))
    ev = report["evidence"]
    lg = ev["ledger"]
    integrity = "VERIFIED - no tampering detected" if lg["ok"] else f"TAMPERING DETECTED at ledger block {lg['first_broken_height']}"
    E.append(Paragraph(f"Tamper-evident ledger status: <b>{integrity}</b> ({lg['blocks']} sealed blocks, head hash "
                       f"<font face='Courier'>{lg['head_hash'][:16]}...</font>).", BODY))
    rd = ev["readings"]
    E.append(Paragraph(f"{rd['n']} readings recorded ({rd['device'] or 0} from devices, {rd['model'] or 0} model-derived), "
                       f"{ev['evidence'] if False else ''}", BODY))
    if lg["tampered_seqs"]:
        E.append(Paragraph(f"<b>Excluded from evidence (unverified):</b> reading sequence(s) {lg['tampered_seqs']}.", BODY))

    E.append(Paragraph("Liability apportionment", H2))
    rows = [["Finding", "Cause", "Party", "Clause", "Share", "Minutes", "Amount (INR)"]]
    for f in report["findings"]:
        rows.append([f["id"], f["cause"].replace("_", " "), f["party"], f["clause"] or "-", f"{f['share_pct']:.1f}%",
                    f"{f['minutes']:.0f}", f"{f['amount_inr']:,.0f}"])
    E.append(_table(rows, widths=[16 * mm, 30 * mm, 24 * mm, 18 * mm, 18 * mm, 20 * mm, 30 * mm]))
    E.append(Spacer(1, 4))
    for f in report["findings"]:
        E.append(Paragraph(f"<b>{f['id']}</b> ({f['party']}): {f['narrative']}", BODY))
        if f.get("clause_text"):
            E.append(Paragraph(f"<i>SLA {f['clause']}:</i> {f['clause_text']}", SMALL))

    E.append(Paragraph("Party totals", H2))
    prows = [["Party", "Share", "Amount (INR)", "Capped at declared value"]]
    for party, p in report["parties"].items():
        prows.append([party, f"{p['share_pct']:.1f}%", f"{p['amount_inr']:,.0f}", "Yes" if p["capped"] else "No"])
    E.append(_table(prows, widths=[40 * mm, 24 * mm, 40 * mm, 50 * mm]))

    E.append(Paragraph("Timeline", H2))
    trows = [["Time (UTC)", "Event"]]
    for item in report["timeline"][:40]:
        trows.append([item["ts"].replace("T", " ").replace("Z", ""), Paragraph(item["label"], SMALL)])
    E.append(_table(trows, widths=[34 * mm, 130 * mm]))

    E.append(Paragraph("Methodology and assumptions", H2))
    for a in report["assumptions"]:
        E.append(Paragraph(f"&bull; {a}", SMALL))
    E.append(Paragraph("&bull; Findings are narrated by a local LLM (Ollama) or, if unavailable, by a deterministic "
                       "template; every number is machine-checked against the apportionment figures before being "
                       "accepted, so the arithmetic above does not depend on the LLM.", SMALL))

    doc.build(E)
    return buf.getvalue()
