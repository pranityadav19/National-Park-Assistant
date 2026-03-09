from pydantic import BaseModel


class ParkOut(BaseModel):
    park_code: str
    full_name: str
    states: str | None = None
    description: str | None = None
    entrance_fee_summary: str | None = None
    operating_hours_summary: str | None = None
    weather_info: str | None = None
    url: str | None = None

    class Config:
        from_attributes = True


class AskRequest(BaseModel):
    question: str
    park_code: str | None = None
    park_name: str | None = None


class Citation(BaseModel):
    source_type: str
    source_url: str
    section: str | None = None


class AskResponse(BaseModel):
    answer: str
    confidence_note: str
    citations: list[Citation]
