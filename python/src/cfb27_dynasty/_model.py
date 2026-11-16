from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base for every response model. Unknown fields from newer servers are
    kept (reachable through ``model_extra``) instead of failing validation."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
