from fastapi import HTTPException
from src.models.entities import Run,Plan

def ensure_run(s,i):
 row=s.get(Run,i)
 if not row:raise HTTPException(404,'模型版本不存在')
 return row
def ensure_plan(s,i):
 row=s.get(Plan,i)
 if not row:raise HTTPException(404,'排机计划不存在')
 return row
