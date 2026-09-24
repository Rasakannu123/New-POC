"""Tests for the cost tracker math."""

from src.doc_extraction import config
from src.doc_extraction.cost import aggregate_records, cost_block, model_cost

SMALL = "mistralai/mistral-small-2603"
MEDIUM = "mistralai/mistral-medium-3.5"
LARGE = "mistralai/mistral-large-2512"


def test_model_cost_matches_pricing_table():
    cost = model_cost(SMALL, 1_250, 350)
    assert cost["input_cost"] == round(1250 * 0.15 / 1_000_000, 12)
    assert cost["output_cost"] == round(350 * 0.60 / 1_000_000, 12)
    assert cost["total_cost"] == cost["input_cost"] + cost["output_cost"]


def test_model_cost_uses_the_model_actually_used():
    small = model_cost(SMALL, 3_750, 1_050)
    medium = model_cost(MEDIUM, 3_750, 1_050)
    large = model_cost(LARGE, 3_750, 1_050)
    assert small["total_cost"] < large["total_cost"] < medium["total_cost"]


def test_unknown_model_falls_back_to_defaults():
    rates = config.model_pricing("some/unknown-model")
    assert rates == {
        "input": config.DEFAULT_PRICE_INPUT,
        "output": config.DEFAULT_PRICE_OUTPUT,
    }


def test_cost_block_sums_pages_and_groups_by_model():
    block = cost_block(
        [
            {"model": MEDIUM, "input_tokens": 1_250, "output_tokens": 350},
            {"model": MEDIUM, "input_tokens": 1_250, "output_tokens": 350},
            {"model": MEDIUM, "input_tokens": 1_250, "output_tokens": 350},
        ]
    )
    totals = block["totals"]
    assert totals["input_tokens"] == 3_750
    assert totals["output_tokens"] == 1_050
    assert totals["input_cost"] == round(3_750 * 1.50 / 1_000_000, 12)
    assert totals["output_cost"] == round(1_050 * 7.50 / 1_000_000, 12)
    assert totals["total_cost"] == totals["input_cost"] + totals["output_cost"]
    assert list(block["by_model"]) == [MEDIUM]


def test_cost_block_mixes_models():
    block = cost_block(
        [
            {"model": SMALL, "input_tokens": 1_000, "output_tokens": 100},
            {"model": LARGE, "input_tokens": 2_000, "output_tokens": 200},
        ]
    )
    assert set(block["by_model"]) == {SMALL, LARGE}
    assert block["totals"]["input_tokens"] == 3_000
    assert block["totals"]["total_cost"] == sum(
        bucket["total_cost"] for bucket in block["by_model"].values()
    )


def test_cost_block_ignores_unnamed_models():
    block = cost_block([{"model": "", "input_tokens": 10, "output_tokens": 5}])
    assert block["by_model"] == {}
    assert block["totals"]["total_cost"] == 0.0


def test_aggregate_records_merges_documents_and_split_blocks():
    summary = aggregate_records(
        [
            {
                "cost": {
                    "totals": {"input_tokens": 100, "output_tokens": 10},
                    "by_model": {
                        SMALL: {
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "input_cost": 0.1,
                            "output_cost": 0.2,
                            "total_cost": 0.3,
                        }
                    },
                }
            },
            {
                "split_gate_cost": {
                    "totals": {"input_tokens": 50, "output_tokens": 5},
                    "by_model": {
                        LARGE: {
                            "input_tokens": 50,
                            "output_tokens": 5,
                            "input_cost": 0.4,
                            "output_cost": 0.6,
                            "total_cost": 1.0,
                        }
                    },
                }
            },
            {"extracted_fields": {}},
        ]
    )
    assert summary["cost_blocks_scanned"] == 2
    assert summary["by_model"][SMALL]["total_cost"] == 0.3
    assert summary["by_model"][LARGE]["total_cost"] == 1.0
    assert summary["totals"]["total_cost"] == 1.3
    assert summary["by_model"][SMALL]["input_rate"] == 0.15
