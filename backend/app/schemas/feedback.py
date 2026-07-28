from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(..., ge=-1, le=1, description="1 点赞, -1 点踩")
    comment: str | None = Field(None, max_length=500)
    feedback_type: (
        Literal[
            "faithfulness_issue",
            "context_insufficient",
            "incompleteness",
            "irrelevance",
            "verbosity",
            "other",
        ]
        | None
    ) = None


class FeedbackOut(BaseModel):
    id: int
    message_id: int
    user_id: int
    rating: int
    comment: str | None
    feedback_type: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackStats(BaseModel):
    total_feedback: int
    positive_rate: float
    negative_rate: float
    by_type: dict[str, int]


class FeedbackDetail(BaseModel):
    id: int
    message_id: int
    rating: int
    comment: str | None
    feedback_type: str | None
    created_at: datetime
    question: str
    answer: str
    session_id: int
    kb_id: int | None

    model_config = ConfigDict(from_attributes=True)
