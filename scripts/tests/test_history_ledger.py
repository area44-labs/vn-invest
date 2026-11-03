"""Unit and boundary tests for Recommendation Ledger."""

import os
import tempfile

import pytest

from scripts.history.ledger import (
    RecommendationLedger,
    extract_ledger_entries_from_recommendations,
)
from scripts.history.models import (
    RecommendationLedgerEntry,
    generate_recommendation_id,
)


@pytest.mark.unit
class TestRecommendationLedgerSuite:
    """Tests for deterministic recommendation identities, persistence, deduplication, and independence from report retention."""

    def test_deterministic_recommendation_identity(self):
        """Recommendation identity is stable and deterministic for identical parameters."""
        id1 = generate_recommendation_id(
            trading_date="2026-10-01",
            symbol="VNM",
            action="BUY",
            model_version="2.0",
            config_hash="abc12345",
        )
        id2 = generate_recommendation_id(
            trading_date="2026-10-01",
            symbol="vnm",
            action="buy",
            model_version="2.0",
            config_hash="abc12345",
        )
        assert id1 == id2
        assert id1.startswith("rec_2026-10-01_VNM_")

    def test_different_actions_produce_different_identities(self):
        """Different recommendation decisions for the same symbol produce distinct identities."""
        id_buy = generate_recommendation_id("2026-10-01", "VNM", "BUY")
        id_sell = generate_recommendation_id("2026-10-01", "VNM", "SELL")
        assert id_buy != id_sell

    def test_decision_differences_produce_different_identities(self):
        """Different target price, reference price, confidence, signal score, or risk produce distinct IDs."""
        base_id = generate_recommendation_id(
            "2026-10-01", "VNM", "BUY", reference_price=70000.0, target_price=75000.0
        )
        diff_price_id = generate_recommendation_id(
            "2026-10-01", "VNM", "BUY", reference_price=71000.0, target_price=75000.0
        )
        diff_tp_id = generate_recommendation_id(
            "2026-10-01", "VNM", "BUY", reference_price=70000.0, target_price=78000.0
        )
        diff_conf_id = generate_recommendation_id(
            "2026-10-01",
            "VNM",
            "BUY",
            reference_price=70000.0,
            target_price=75000.0,
            confidence=0.9,
        )
        diff_risk_id = generate_recommendation_id(
            "2026-10-01",
            "VNM",
            "BUY",
            reference_price=70000.0,
            target_price=75000.0,
            risk_level="HIGH",
        )
        assert base_id != diff_price_id
        assert base_id != diff_tp_id
        assert base_id != diff_conf_id
        assert base_id != diff_risk_id

    def test_extract_ledger_entries(self):
        """Extract RecommendationLedgerEntry objects correctly maps domain fields."""
        recs = [
            {
                "symbol": "FPT",
                "action": "BUY",
                "trade_plan": {"current_price": 105000.0, "tp1": 115000.0},
                "confidence": 0.85,
                "signal_score": 78.5,
                "risk_adjusted_score": 75.0,
                "risk_level": "LOW",
                "reasons": ["Strong momentum"],
            }
        ]
        entries = extract_ledger_entries_from_recommendations(recs, "2026-10-01")
        assert len(entries) == 1
        e = entries[0]
        assert e.symbol == "FPT"
        assert e.action == "BUY"
        assert e.reference_price == 105000.0
        assert e.target_price == 115000.0
        assert e.confidence == 0.85
        assert e.reasons == ("Strong momentum",)

    def test_ledger_partition_persistence_and_deduplication(self):
        """Writing the same recommendation repeatedly does not append duplicates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = RecommendationLedger(tmpdir)

            recs = [
                {
                    "symbol": "HPG",
                    "action": "BUY",
                    "trade_plan": {"current_price": 28000.0, "tp1": 31000.0},
                }
            ]
            entries1 = extract_ledger_entries_from_recommendations(recs, "2026-10-01")

            # Stage once
            ledger.stage_partition_entries(tmpdir, "2026-10-01", entries1)
            loaded1 = ledger.load_partition("2026-10-01")
            assert len(loaded1) == 1

            # Stage again with same entry (idempotent)
            ledger.stage_partition_entries(tmpdir, "2026-10-01", entries1)
            loaded2 = ledger.load_partition("2026-10-01")
            assert len(loaded2) == 1
            assert loaded2[0].recommendation_id == entries1[0].recommendation_id

    def test_ledger_conflict_detection_on_different_payload(self):
        """Attempting to overwrite an existing record with different payload raises LedgerConflictError."""
        from scripts.history.models import LedgerConflictError

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = RecommendationLedger(tmpdir)
            entry1 = RecommendationLedgerEntry(
                recommendation_id="rec_2026-10-01_HPG_1234567890ab",
                symbol="HPG",
                trading_date="2026-10-01",
                action="BUY",
                reference_price=28000.0,
            )
            ledger.stage_partition_entries(tmpdir, "2026-10-01", [entry1])

            # Conflicting entry with same ID but different payload
            conflicting_entry = RecommendationLedgerEntry(
                recommendation_id="rec_2026-10-01_HPG_1234567890ab",
                symbol="HPG",
                trading_date="2026-10-01",
                action="BUY",
                reference_price=35000.0,  # Changed price!
            )
            with pytest.raises(LedgerConflictError):
                ledger.stage_partition_entries(tmpdir, "2026-10-01", [conflicting_entry])

    def test_ledger_preserves_multiple_recommendations_for_same_symbol(self):
        """Multiple distinct recommendations for the same symbol are both preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = RecommendationLedger(tmpdir)
            entry_buy = RecommendationLedgerEntry(
                recommendation_id="rec_2026-10-01_HPG_aaaa11112222",
                symbol="HPG",
                trading_date="2026-10-01",
                action="BUY",
                reference_price=28000.0,
            )
            entry_watch = RecommendationLedgerEntry(
                recommendation_id="rec_2026-10-01_HPG_bbbb33334444",
                symbol="HPG",
                trading_date="2026-10-01",
                action="WATCH",
                reference_price=28000.0,
            )
            ledger.stage_partition_entries(tmpdir, "2026-10-01", [entry_buy, entry_watch])
            loaded = ledger.load_partition("2026-10-01")
            assert len(loaded) == 2
            assert {e.action for e in loaded} == {"BUY", "WATCH"}

    def test_ledger_preserves_historical_recommendations_after_report_pruning(self):
        """Daily report cleanup does not delete Recommendation Ledger records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = RecommendationLedger(tmpdir)
            entries = extract_ledger_entries_from_recommendations(
                [{"symbol": "VIC", "action": "AVOID"}], "2026-08-01"
            )
            ledger.stage_partition_entries(tmpdir, "2026-08-01", entries)

            # Even if history/2026-08-01.json does not exist, ledger remains
            assert os.path.exists(ledger.conventions.get_ledger_partition_path("2026-08-01"))
            assert len(ledger.load_partition("2026-08-01")) == 1

    def test_invalid_ledger_record_rejected(self):
        """Invalid fields in RecommendationLedgerEntry fail validation immediately."""
        with pytest.raises(ValueError):
            RecommendationLedgerEntry(
                recommendation_id="",
                symbol="FPT",
                trading_date="2026-10-01",
                action="BUY",
            )

        with pytest.raises(ValueError):
            RecommendationLedgerEntry(
                recommendation_id="rec_1",
                symbol="FPT",
                trading_date="INVALID_DATE",
                action="BUY",
            )
