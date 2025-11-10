from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from bson import ObjectId

# Database utilities are pre-configured in this environment
# Schemas must be defined in schemas.py
from database import db, create_document, get_documents
from schemas import User, Course, Task, Mood, Post, Reply

app = FastAPI(title="UNIVO API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility functions

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


def now_ts() -> datetime:
    return datetime.utcnow()


# Health / test
@app.get("/test")
async def test_connection():
    # try a simple round trip
    try:
        await db.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Users
class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str


@app.post("/users", response_model=User)
async def create_or_get_user(payload: CreateUserRequest):
    existing = await db["user"].find_one({"email": payload.email})
    if existing:
        return User(**existing)
    data = User(
        email=payload.email,
        name=payload.name,
        xp=0,
        streak=0,
        last_checkin=None,
        created_at=now_ts(),
        updated_at=now_ts(),
    ).model_dump()
    doc = await create_document("user", data)
    return User(**doc)


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    doc = await db["user"].find_one({"_id": oid(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**doc)


# Courses
@app.post("/courses", response_model=Course)
async def create_course(course: Course):
    # Ensure user exists
    u = await db["user"].find_one({"_id": oid(course.user_id)})
    if not u:
        raise HTTPException(status_code=400, detail="User not found")
    data = course.model_dump()
    data["created_at"] = now_ts()
    data["updated_at"] = now_ts()
    doc = await create_document("course", data)
    return Course(**doc)


@app.get("/courses", response_model=List[Course])
async def list_courses(user_id: str = Query(...)):
    docs = await get_documents("course", {"user_id": user_id}, limit=200)
    return [Course(**d) for d in docs]


# Tasks
@app.post("/tasks", response_model=Task)
async def create_task(task: Task):
    # Validate references
    u = await db["user"].find_one({"_id": oid(task.user_id)})
    if not u:
        raise HTTPException(status_code=400, detail="User not found")
    if task.course_id:
        c = await db["course"].find_one({"_id": oid(task.course_id)})
        if not c:
            raise HTTPException(status_code=400, detail="Course not found")
    data = task.model_dump()
    data["status"] = data.get("status") or "pending"
    data["created_at"] = now_ts()
    data["updated_at"] = now_ts()
    if "xp_value" not in data or data["xp_value"] is None:
        data["xp_value"] = 10
    doc = await create_document("task", data)
    return Task(**doc)


@app.get("/tasks", response_model=List[Task])
async def list_tasks(user_id: str = Query(...), course_id: Optional[str] = None, status: Optional[str] = None):
    q = {"user_id": user_id}
    if course_id:
        q["course_id"] = course_id
    if status:
        q["status"] = status
    docs = await get_documents("task", q, limit=500)
    return [Task(**d) for d in docs]


class CompleteTaskResponse(BaseModel):
    xp_awarded: int
    total_xp: int
    streak: int
    task: Task


@app.patch("/tasks/{task_id}/complete", response_model=CompleteTaskResponse)
async def complete_task(task_id: str):
    t = await db["task"].find_one({"_id": oid(task_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.get("status") == "completed":
        # idempotent
        user = await db["user"].find_one({"_id": oid(t["user_id"])})
        return CompleteTaskResponse(
            xp_awarded=0,
            total_xp=user.get("xp", 0),
            streak=user.get("streak", 0),
            task=Task(**t),
        )

    # Mark complete
    await db["task"].update_one({"_id": t["_id"]}, {"$set": {"status": "completed", "updated_at": now_ts()}})

    # Award XP and update streak basics
    xp_gain = int(t.get("xp_value", 10))
    user = await db["user"].find_one({"_id": oid(t["user_id"])})
    new_xp = int(user.get("xp", 0)) + xp_gain

    # Simple daily streak: if last_checkin is today, keep, else if yesterday or None -> increment, else reset
    today = date.today()
    last = user.get("last_checkin")
    if last and isinstance(last, datetime):
        last_date = last.date()
    else:
        last_date = None

    if last_date == today:
        new_streak = int(user.get("streak", 0))
    elif last_date == today - timedelta(days=1) or last_date is None:
        new_streak = int(user.get("streak", 0)) + 1
    else:
        new_streak = 1

    await db["user"].update_one(
        {"_id": user["_id"]},
        {"$set": {"xp": new_xp, "streak": new_streak, "last_checkin": datetime.utcnow(), "updated_at": now_ts()}},
    )

    # Reload docs
    t2 = await db["task"].find_one({"_id": oid(task_id)})
    u2 = await db["user"].find_one({"_id": user["_id"]})

    return CompleteTaskResponse(
        xp_awarded=xp_gain,
        total_xp=u2.get("xp", 0),
        streak=u2.get("streak", 0),
        task=Task(**t2),
    )


# Mood check-ins
class MoodRequest(BaseModel):
    user_id: str
    mood: str
    note: Optional[str] = None


@app.post("/moods", response_model=Mood)
async def create_mood(payload: MoodRequest):
    # Validate user
    u = await db["user"].find_one({"_id": oid(payload.user_id)})
    if not u:
        raise HTTPException(status_code=400, detail="User not found")
    data = Mood(user_id=payload.user_id, mood=payload.mood, note=payload.note, created_at=now_ts()).model_dump()
    doc = await create_document("mood", data)

    # Update last_checkin for streak continuity
    today = date.today()
    last = u.get("last_checkin")
    if not last or (isinstance(last, datetime) and last.date() != today):
        # Only set date if different to preserve increment logic on task completion
        await db["user"].update_one({"_id": u["_id"]}, {"$set": {"last_checkin": datetime.utcnow(), "updated_at": now_ts()}})

    return Mood(**doc)


# Flamo Lite suggestions
class SuggestionResponse(BaseModel):
    message: str


@app.get("/flamo/suggest", response_model=SuggestionResponse)
async def suggest_next(user_id: str = Query(...)):
    # Pull today's mood
    today = date.today()
    moods = await get_documents("mood", {"user_id": user_id}, limit=10)
    today_mood = None
    for m in moods:
        ts = m.get("created_at")
        if isinstance(ts, datetime) and ts.date() == today:
            today_mood = m
            break

    # Get pending tasks sorted by due date
    tasks = await db["task"].find({"user_id": user_id, "status": {"$ne": "completed"}}).sort("due_date", 1).to_list(length=50)

    if not tasks:
        return SuggestionResponse(message="No pending tasks. Consider a 10-minute mindfulness break or review notes.")

    next_task = tasks[0]
    mood = (today_mood or {}).get("mood", "neutral")
    due = next_task.get("due_date")
    if isinstance(due, datetime):
        hours_left = int((due - datetime.utcnow()).total_seconds() // 3600)
    else:
        hours_left = None

    if mood in ["tired", "stressed"]:
        base = "You seem a bit off today. Take a 10-minute reset, then tackle: "
    elif mood in ["happy", "motivated"]:
        base = "You're on a roll! Next up: "
    else:
        base = "Here's your next best step: "

    extra = f" due in {hours_left}h" if hours_left is not None else ""
    return SuggestionResponse(message=f"{base}{next_task.get('title')}{extra}.")


# Forum (Community Q&A)
@app.post("/posts", response_model=Post)
async def create_post(post: Post):
    # Validate user
    u = await db["user"].find_one({"_id": oid(post.user_id)})
    if not u:
        raise HTTPException(status_code=400, detail="User not found")
    data = post.model_dump()
    data["created_at"] = now_ts()
    data["updated_at"] = now_ts()
    data["replies"] = []
    doc = await create_document("post", data)
    return Post(**doc)


@app.get("/posts", response_model=List[Post])
async def list_posts(limit: int = 50):
    docs = await db["post"].find({}).sort("created_at", -1).to_list(length=min(limit, 100))
    return [Post(**d) for d in docs]


class ReplyRequest(BaseModel):
    user_id: str
    content: str


@app.post("/posts/{post_id}/reply", response_model=Post)
async def add_reply(post_id: str, reply: ReplyRequest):
    # Validate user
    u = await db["user"].find_one({"_id": oid(reply.user_id)})
    if not u:
        raise HTTPException(status_code=400, detail="User not found")
    rep = Reply(user_id=reply.user_id, content=reply.content, created_at=now_ts()).model_dump()
    res = await db["post"].find_one_and_update(
        {"_id": oid(post_id)},
        {"$push": {"replies": rep}, "$set": {"updated_at": now_ts()}},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="Post not found")
    return Post(**res)


# Leaderboard
class Leader(BaseModel):
    user_id: str
    name: str
    xp: int
    streak: int


@app.get("/leaderboard", response_model=List[Leader])
async def leaderboard(limit: int = 10):
    users = await db["user"].find({}).sort("xp", -1).to_list(length=min(limit, 50))
    return [Leader(user_id=str(u.get("_id")), name=u.get("name"), xp=int(u.get("xp", 0)), streak=int(u.get("streak", 0))) for u in users]
