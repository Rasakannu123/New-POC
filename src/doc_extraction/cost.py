"""
Cost Tracker
------------
Token accounting and USD cost math for every model call.

Per call:   cost = tokens x rate / 1_000_000  (rate = USD per 1M tokens)
Per record: tokens are summed across pages, grouped by the model used, and
            priced per model because rates differ.
Globally:   the same per-model blocks from all records are summed.
"""

from __future__ import annotations

from src.doc_extraction import config

TOKENS_PER_MILLION = 1_000_000


def _empty_bucket() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0,
    }


def model_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """Cost block for one model's token usage."""
    rates = config.model_pricing(model)
    input_cost = (int(input_tokens) * rates["input"]) / TOKENS_PER_MILLION
    output_cost = (int(output_tokens) * rates["output"]) / TOKENS_PER_MILLION
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
    }


def cost_block(usages: list[dict]) -> dict:
    """Aggregate [{model, input_tokens, output_tokens}, ...] into a cost block."""
    by_model: dict[str, dict] = {}
    for usage in usages:
        model = str(usage.get("model") or "")
        if not model:
            continue
        bucket = by_model.setdefault(model, _empty_bucket())
        bucket["input_tokens"] += int(usage.get("input_tokens") or 0)
        bucket["output_tokens"] += int(usage.get("output_tokens") or 0)

    for model, bucket in by_model.items():
        rates = config.model_pricing(model)
        priced = model_cost(model, bucket["input_tokens"], bucket["output_tokens"])
        bucket["input_cost"] = priced["input_cost"]
        bucket["output_cost"] = priced["output_cost"]
        bucket["total_cost"] = priced["total_cost"]
        bucket["input_rate"] = rates["input"]
        bucket["output_rate"] = rates["output"]

    totals = _empty_bucket()
    for bucket in by_model.values():
        totals["input_tokens"] += bucket["input_tokens"]
        totals["output_tokens"] += bucket["output_tokens"]
        totals["input_cost"] += bucket["input_cost"]
        totals["output_cost"] += bucket["output_cost"]
        totals["total_cost"] += bucket["total_cost"]

    return {"totals": totals, "by_model": by_model}


def aggregate_records(records: list[dict]) -> dict:
    """Global tracker: merge cost blocks from all stored records."""
    by_model: dict[str, dict] = {}
    scanned = 0

    for record in records:
        for block in (record.get("cost"), record.get("split_gate_cost")):
            if not isinstance(block, dict):
                continue
            scanned += 1
            for model, bucket in (block.get("by_model") or {}).items():
                target = by_model.setdefault(model, _empty_bucket())
                target["input_tokens"] += int(bucket.get("input_tokens") or 0)
                target["output_tokens"] += int(bucket.get("output_tokens") or 0)
                target["input_cost"] += float(bucket.get("input_cost") or 0.0)
                target["output_cost"] += float(bucket.get("output_cost") or 0.0)
                target["total_cost"] += float(bucket.get("total_cost") or 0.0)

    totals = _empty_bucket()
    for model, bucket in by_model.items():
        rates = config.model_pricing(model)
        bucket["input_rate"] = rates["input"]
        bucket["output_rate"] = rates["output"]
        totals["input_tokens"] += bucket["input_tokens"]
        totals["output_tokens"] += bucket["output_tokens"]
        totals["input_cost"] += bucket["input_cost"]
        totals["output_cost"] += bucket["output_cost"]
        totals["total_cost"] += bucket["total_cost"]

    return {
        "totals": totals,
        "by_model": by_model,
        "cost_blocks_scanned": scanned,
    }
