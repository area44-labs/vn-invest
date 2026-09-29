"""Domain contract for Pipeline Execution Result."""

from typing import Any, Self


class PipelineResult(tuple):
    """Immutable domain representation of a pipeline execution result.

    Preserves 3-element tuple unpacking backward compatibility `(recs_payload, market_payload, history_payload)`
    while exposing benchmark DataFrames and universe audit diagnostic attributes.
    """

    def __new__(
        cls,
        recs_data: dict,
        market_data: dict,
        history_data: dict,
        df_vnindex: Any = None,
        df_vn30: Any = None,
        universe_audit: dict | None = None,
    ) -> Self:
        obj = super().__new__(cls, (recs_data, market_data, history_data))
        obj.recommendations_payload = recs_data
        obj.market_payload = market_data
        obj.history_payload = history_data
        obj.df_vnindex = df_vnindex
        obj.df_vn30 = df_vn30
        obj.universe_audit = universe_audit
        return obj

    def to_dict(self) -> dict[str, Any]:
        """Convert PipelineResult contract to dictionary representation."""
        res: dict[str, Any] = {
            "recommendations": self.recommendations_payload,
            "market": self.market_payload,
            "history": self.history_payload,
        }
        if self.universe_audit:
            res["universe_audit"] = self.universe_audit
        return res
