"""Domain contract for Pipeline Execution Result."""

from typing import Any, Self


class PipelineResult(tuple):
    """Immutable domain representation of a pipeline execution result.

    Preserves 3-element tuple unpacking backward compatibility `(recs_payload, market_payload, history_payload)`
    while exposing benchmark DataFrames, universe audit diagnostics, and monitoring attributes.
    """

    def __new__(
        cls,
        recs_data: dict,
        market_data: dict,
        history_data: dict,
        df_vnindex: Any = None,
        df_vn30: Any = None,
        universe_audit: dict | None = None,
        monitoring_result: Any = None,
        monitoring_dict: dict | None = None,
    ) -> Self:
        instance = super().__new__(cls, (recs_data, market_data, history_data))
        instance.recommendations_payload = recs_data
        instance.market_payload = market_data
        instance.history_payload = history_data
        instance.df_vnindex = df_vnindex
        instance.df_vn30 = df_vn30
        instance.universe_audit = universe_audit
        instance.monitoring_result = monitoring_result
        instance.monitoring_dict = monitoring_dict
        return instance

    def to_dict(self) -> dict[str, Any]:
        """Convert PipelineResult contract to dictionary representation."""
        res: dict[str, Any] = {
            "recommendations": self.recommendations_payload,
            "market": self.market_payload,
            "history": self.history_payload,
        }
        if self.universe_audit:
            res["universe_audit"] = self.universe_audit
        if self.monitoring_dict:
            res["monitoring"] = self.monitoring_dict
        return res
