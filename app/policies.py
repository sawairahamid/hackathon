from __future__ import annotations

from typing import Any


class BusinessPolicyEngine:
    def __init__(self, constraints: dict[str, Any] | None = None) -> None:
        # Defaults, could be loaded from config
        self.policies = {
            "maximum_budget_usd": 20000,
            "maximum_budget_pkr": 10000000,
            "minimum_supplier_rating": 4.0,
            "minimum_warranty_months": 12,
            "maximum_delivery_days": 14,
            "approval_required": True
        }
        if constraints:
            self.policies.update(constraints)

    def evaluate_budget(self, currency: str, total_amount: float) -> tuple[bool, str]:
        key = f"maximum_budget_{currency.lower()}"
        max_budget = self.policies.get(key)
        if max_budget is None:
            return True, f"No budget constraint for {currency}"
        if total_amount <= max_budget:
            return True, f"{total_amount:,.2f} <= {max_budget:,.2f}"
        return False, f"Policy maximum exceeded by {total_amount - max_budget:,.2f} {currency}"

    def evaluate_supplier(self, supplier_data: dict[str, Any]) -> tuple[bool, str]:
        # Rating
        if "rating" in supplier_data:
            if supplier_data["rating"] < self.policies["minimum_supplier_rating"]:
                return False, f"Supplier rating {supplier_data['rating']} is below minimum {self.policies['minimum_supplier_rating']}"
        # Warranty
        if "warranty_months" in supplier_data:
            if supplier_data["warranty_months"] < self.policies["minimum_warranty_months"]:
                return False, f"Warranty {supplier_data['warranty_months']} months is below minimum {self.policies['minimum_warranty_months']}"
        # Delivery
        if "delivery_days" in supplier_data:
            if supplier_data["delivery_days"] > self.policies["maximum_delivery_days"]:
                return False, f"Delivery {supplier_data['delivery_days']} days exceeds maximum {self.policies['maximum_delivery_days']}"
        
        return True, "Supplier meets all business policies."

# Global instance for standard evaluation
default_policy_engine = BusinessPolicyEngine()
