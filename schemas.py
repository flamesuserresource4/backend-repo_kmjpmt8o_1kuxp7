from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr

# Each model corresponds to a MongoDB collection named by the class name lowercased

class User(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    email: EmailStr
    name: str
    xp: int = 0
    streak: int = 0
    last_checkin: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class Course(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    title: str
    code: Optional[str] = None
    color: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class Task(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    title: str
    course_id: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str = "pending"  # pending | completed
    xp_value: Optional[int] = 10
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class Mood(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    mood: str  # happy, neutral, tired, stressed, motivated
    note: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class Reply(BaseModel):
    user_id: str
    content: str
    created_at: datetime


class Post(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    title: str
    content: str
    replies: List[Reply] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
