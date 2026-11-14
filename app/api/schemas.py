from pydantic import BaseModel, ConfigDict, Field

from app.services.dto import ItemInput, OrderCommand


class ItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    menu_item_id: int = Field(gt=0, strict=True)
    quantity: int = Field(ge=1, le=20, strict=True)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cafe_id: int = Field(gt=0, strict=True)
    items: list[ItemRequest] = Field(min_length=1, max_length=20)

    def item_inputs(self) -> list[ItemInput]:
        return [ItemInput(x.menu_item_id, x.quantity) for x in self.items]


class OrderRequest(PreviewRequest):
    slot_id: int = Field(gt=0, strict=True)
    expected_total_minor: int = Field(gt=0, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=64)

    def command(self) -> OrderCommand:
        return OrderCommand(self.cafe_id, self.slot_id, self.item_inputs(), self.expected_total_minor, self.idempotency_key)
