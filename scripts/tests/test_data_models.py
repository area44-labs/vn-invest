"""Unit tests for CanonicalMarketData model in scripts/data/models.py."""

import pandas as pd
import pytest

from scripts.data.models import FORBIDDEN_PROVIDER_FIELDS, CanonicalMarketData
from scripts.domain.data_quality import DataQuality
from scripts.domain.ohlcv import OHLCVData


@pytest.mark.unit
class TestCanonicalMarketDataModel:
    """Test suite for CanonicalMarketData model contracts and boundaries."""

    def test_basic_instantiation(self):
        rec = OHLCVData(
            date="2025-01-02", open=100.0, high=105.0, low=99.0, close=102.0, volume=1000.0
        )
        cmd = CanonicalMarketData(
            symbol="fpt",
            records=(rec,),
            data_as_of="2025-01-02",
            source_tag="REAL_DATA",
        )
        assert cmd.symbol == "FPT"
        assert len(cmd.records) == 1
        assert cmd.data_as_of == "2025-01-02"
        assert cmd.source_tag == "REAL_DATA"
        assert not hasattr(cmd, "df")

    def test_forbid_provider_fields_in_from_dict(self):
        for forbidden in FORBIDDEN_PROVIDER_FIELDS:
            data = {
                "symbol": "FPT",
                "data_as_of": "2025-01-02",
                forbidden: "some_provider_payload",
            }
            with pytest.raises(ValueError) as ctx:
                CanonicalMarketData.from_dict(data)
            assert "forbidden provider keys present" in str(ctx.value)

    def test_from_df_and_to_df_roundtrip(self):
        df_raw = pd.DataFrame(
            {
                "time": ["2025-01-02", "2025-01-03"],
                "open": [100.0, 102.0],
                "high": [105.0, 107.0],
                "low": [99.0, 101.0],
                "close": [102.0, 106.0],
                "volume": [1000.0, 1500.0],
            }
        )
        cmd = CanonicalMarketData.from_df("VCB", df_raw)
        assert cmd.symbol == "VCB"
        assert cmd.data_as_of == "2025-01-03"
        assert len(cmd.records) == 2

        df_out = cmd.to_df()
        assert "date" in df_out.columns
        assert len(df_out) == 2
        assert df_out["close"].iloc[-1] == 106.0

    def test_to_dict_and_from_dict_roundtrip(self):
        rec = OHLCVData(
            date="2025-01-02", open=100.0, high=105.0, low=99.0, close=102.0, volume=1000.0
        )
        dq = DataQuality(status="SUFFICIENT", valid_row_count=1)
        cmd = CanonicalMarketData(
            symbol="HPG",
            records=(rec,),
            data_as_of="2025-01-02",
            source_tag="REAL_DATA",
            data_quality=dq,
        )
        d = cmd.to_dict()
        for forbidden in FORBIDDEN_PROVIDER_FIELDS:
            assert forbidden not in d

        cmd_restored = CanonicalMarketData.from_dict(d)
        assert cmd_restored.symbol == "HPG"
        assert cmd_restored.data_as_of == "2025-01-02"
        assert cmd_restored.data_quality.status == "SUFFICIENT"

    def test_invalid_symbol_and_dates(self):
        with pytest.raises(ValueError):
            CanonicalMarketData(symbol="")
        with pytest.raises(ValueError):
            CanonicalMarketData(symbol="FPT", data_as_of="02-01-2025")
