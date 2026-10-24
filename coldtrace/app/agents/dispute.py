"""Multi-agent dispute pipeline (LLM-agents / disputes track).

Stages, each an independent, auditable step:
  1. Evidence Collector   - gathers readings, ledger status, custody events, alerts (tools.collect_evidence)
  2. Timeline Reconstructor - orders everything into a single evidence-linked timeline (tools.build_timeline)
  3. SLA Analyst          - retrieves the relevant contract clauses via BM25 full-text search (tools.retrieve_clauses)
  4. Liability Apportioner - runs the deterministic counterfactual engine (tools.apportion_liability); the LLM
                             only narrates the numbers the code already produced, per finding, citing clause + evidence
  5. Report Writer        - assembles the incident docket
  6. Verifier             - re-checks every number quoted in the narrative against the apportionment JSON; any
                             ungrounded figure is stripped and replaced with the deterministic wording
No stage lets the LLM invent a number: apportion_liability is pure arithmetic and the narrative stages are
grounded-checked by orchestrator.numbers_grounded before being accepted.
"""
from __future__ import annotations

import logging

from .. import db
from ..services import ingest
from . import tools
from .orchestrator import Run, numbers_grounded

log = logging.getLogger("coldtrace.dispute")

FINDING_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["narrative"],
                  "properties": {"narrative": {"type": "string", "maxLength": 380}}}
SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "recommendation"],
                  "properties": {"summary": {"type": "string", "maxLength": 500}, "recommendation": {"type": "string", "maxLength": 300}}}

FINDING_SYSTEM = ("You write one sentence of a cold-chain liability report for the given finding. Use ONLY the numbers, "
                  "party names and clause numbers present in FACTS. Do not compute, round differently, or add any figure "
                  "not present in FACTS. State the party, the clause, the share and the amount.")
SUMMARY_SYSTEM = ("You write the executive summary of a cold-chain liability report already computed by deterministic code. "
                  "Use ONLY numbers present in FACTS. Do not add new facts, causes or figures.")


def _finding_fallback(f: dict) -> dict:
    clause = f" (SLA {f['clause']})" if f["clause"] else ""
    return {"narrative": f"{f['description']}{clause}: {f['share_pct']:.1f}% of the loss, INR {f['amount_inr']:,.0f}, "
                         f"attributed to {f['party']}, covering reading(s) {f['seq_ranges']}."}


def _summary_fallback(totals: dict | None, parties: dict) -> dict:
    if totals is None:
        return {"summary": "There are not yet enough verified readings on this shipment to assess a loss "
                           "(at least 3 are needed). No liability can be apportioned until more telemetry is recorded.",
                "recommendation": "Advance the shipment (or wait for more device readings) and use Recompute once "
                                  "at least 3 verified readings exist."}
    lead = max(parties.items(), key=lambda kv: kv[1]["amount_inr"]) if parties else None
    lead_txt = f" The largest share falls to {lead[0]} at INR {lead[1]['amount_inr']:,.0f}." if lead else ""
    return {"summary": f"Assessed loss is {totals['loss_pct']:.2f}% of declared value (INR {totals['loss_inr']:,.0f}), "
                       f"with {totals['minutes_out_of_band']:.0f} minutes outside the allowed band.{lead_txt}",
            "recommendation": "Settle per the apportionment below; parties may request re-computation if new verified readings are added."}


def run_dispute(dispute_id: int) -> dict:
    d = db.one("SELECT * FROM disputes WHERE id=?", (dispute_id,))
    sid = d["shipment_id"]
    run = Run("dispute", shipment_id=sid, dispute_id=dispute_id)
    try:
        evidence = run.tool(tools.registry, "collect_evidence", shipment_id=sid)
        timeline = run.tool(tools.registry, "build_timeline", shipment_id=sid)
        appo = run.tool(tools.registry, "apportion_liability", shipment_id=sid)
        clause_lookup = {}
        for f in appo["findings"]:
            hits = run.tool(tools.registry, "retrieve_clauses", query=tools.cause_query(f["cause"]), k=2)
            clause_lookup[f["id"]] = hits
            run.rule(f"cite_check_{f['id']}", lambda f=f, hits=hits: any(h["clause_no"] == f["clause"] for h in hits) if f["clause"] else True,
                     note="confirm the retrieved clause matches the finding's cited clause")

        narratives = {}
        for f in appo["findings"]:
            out = run.llm_step(f"narrate_{f['id']}", FINDING_SYSTEM, f, "Write the narrative sentence for this finding.",
                               FINDING_SCHEMA, lambda f=f: _finding_fallback(f), text_fields=("narrative",))
            narratives[f["id"]] = out["narrative"]

        summary = run.llm_step("summary", SUMMARY_SYSTEM, {"totals": appo["totals"], "parties": appo["parties"]},
                               "Write the executive summary and recommendation.", SUMMARY_SCHEMA,
                               lambda: _summary_fallback(appo["totals"], appo["parties"]), text_fields=("summary", "recommendation"))

        report = {
            "dispute_id": dispute_id, "shipment_id": sid, "contract_id": appo["contract_id"],
            "generated_at": ingest.now_iso(), "claimant": d["claimant"], "respondent": d["respondent"],
            "summary": summary["summary"], "recommendation": summary["recommendation"],
            "generated_by": {"summary": summary["_generated_by"]},
            "evidence": evidence, "timeline": timeline,
            "totals": appo["totals"], "parties": appo["parties"],
            "findings": [dict(f, narrative=narratives[f["id"]], clause_text=next((h["body"] for h in clause_lookup.get(f["id"], []) if h["clause_no"] == f["clause"]), None))
                        for f in appo["findings"]],
            "assumptions": appo["assumptions"],
        }
        db.run("UPDATE disputes SET status='resolved', report_json=? WHERE id=?", (db.jdump(report), dispute_id))
        run.finish("done", {"dispute_id": dispute_id})
        return report
    except Exception as e:  # noqa: BLE001
        log.exception("dispute pipeline failed")
        db.run("UPDATE disputes SET status='error' WHERE id=?", (dispute_id,))
        run.finish("failed", {"error": str(e)})
        raise
