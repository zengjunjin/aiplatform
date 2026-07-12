from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=-1, le=1, description="1 点赞, -1 点踩")
    comment: Optional[str] = Field(None, max_length=500)
    feedback_type: Optional[str] = Field(None, max_length=30)


class FeedbackOut(BaseModel):
    id: int
    message_id: int
    user_id: int
    rating: int
    comment: Optional[str]
    feedback_type: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackStats(BaseModel):
    total_feedback: int
    positive_rate: float
    negative_rate: float
    by_type: dict[str, int]


class FeedbackDetail(BaseModel):
    id: int
    message_id: int
    rating: int
    comment: Optional[str]
    feedback_type: Optional[str]
    created_at: datetime
    question: str
    answer: str
    session_id: int
    kb_id: Optional[int]

    class Config:
        from_attributes = True