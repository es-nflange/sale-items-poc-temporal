from dataclasses import dataclass


@dataclass
class SaleItem:
    sale_item_id: str
    current_status: str
    quantity: int
