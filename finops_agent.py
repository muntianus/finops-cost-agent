from dataclasses import dataclass

@dataclass
class RightsizingRecommendation:
    resource_id: str
    current_sku: str
    recommended_sku: str
    monthly_savings_usd: float

def analyze_nat_egress(gb_processed: float, rate_per_gb: float = 0.045) -> dict:
    monthly_cost = gb_processed * rate_per_gb
    return {
        "gb_processed": gb_processed,
        "estimated_monthly_usd": round(monthly_cost, 2),
        "recommend_vpc_endpoint": monthly_cost > 50.0,
    }
