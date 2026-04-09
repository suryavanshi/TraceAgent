from pydantic import BaseModel, Field


class DesignIR(BaseModel):
    design_id: str
    revision: int = Field(ge=0)
    nets: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
