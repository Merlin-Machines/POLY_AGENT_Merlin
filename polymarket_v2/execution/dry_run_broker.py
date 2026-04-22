from datetime import datetime, timezone

from polymarket_v2.domain.models import Opportunity
from polymarket_v2.execution.broker import Broker


class DryRunBroker(Broker):
    def place(self, opportunity: Opportunity) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return (
            f"dryrun-{ts}-{opportunity.market_id[:8]}-"
            f"{opportunity.side.value.lower()}-{int(opportunity.size_usd * 100)}"
        )
