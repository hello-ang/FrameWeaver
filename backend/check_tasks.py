import json
from app.database import SessionLocal
from app.models.task import Task
db = SessionLocal()
tasks = db.query(Task).order_by(Task.created_at.desc()).limit(14).all()
print(json.dumps([{"id": t.id, "status": getattr(t.status, 'value', str(t.status)), "type": getattr(t.task_type, 'value', str(t.task_type))} for t in tasks], indent=2))
