from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any, Optional
from app.api.deps import get_current_user
from app.models.user import UserInDB
from app.schemas.response import SuccessResponse
from app.models.quiz import QuizBase, QuizInDB
from app.services.quiz import quiz_service

router = APIRouter()

@router.post("/", response_model=SuccessResponse)
async def create_quiz(
    obj_in: QuizBase,
    current_user: UserInDB = Depends(get_current_user)
):
    obj = await quiz_service.create(obj_in, current_user.id)
    return SuccessResponse(message="Quiz created successfully", data=obj.model_dump())

@router.get("/", response_model=SuccessResponse)
async def get_all_quizs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: Optional[str] = Query(None, description="Field to sort by (e.g. created_at)"),
    order: Optional[int] = Query(-1, description="1 for ascending, -1 for descending"),
    # Generic filters can be passed as a JSON string or we can use specific query params
    # For MVP we just pass some common ones if they exist, or we can parse request.query_params
    current_user: UserInDB = Depends(get_current_user)
):
    # In a real app we'd parse all query params into a filters dict.
    filters = {}
    sort = [(sort_by, order)] if sort_by else None
    
    objs = await quiz_service.get_by_user(current_user.id, skip=skip, limit=limit, filters=filters, sort=sort)
    return SuccessResponse(
        message="Quizs retrieved successfully", 
        data=[obj.model_dump() for obj in objs]
    )

@router.get("/{id}", response_model=SuccessResponse)
async def get_quiz(id: str, current_user: UserInDB = Depends(get_current_user)):
    obj = await quiz_service.get_by_id(id, current_user.id)
    if not obj:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return SuccessResponse(message="Quiz retrieved successfully", data=obj.model_dump())

@router.put("/{id}", response_model=SuccessResponse)
async def update_quiz(
    id: str,
    update_data: Dict[str, Any],
    current_user: UserInDB = Depends(get_current_user)
):
    updated_obj = await quiz_service.update(id, current_user.id, update_data)
    if not updated_obj:
        raise HTTPException(status_code=404, detail="Quiz not found or update failed")
    return SuccessResponse(message="Quiz updated successfully", data=updated_obj.model_dump())

@router.delete("/{id}", response_model=SuccessResponse)
async def delete_quiz(id: str, current_user: UserInDB = Depends(get_current_user)):
    success = await quiz_service.delete(id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or delete failed")
    return SuccessResponse(message="Quiz deleted successfully")

from pydantic import BaseModel as PydanticBaseModel, Field, model_validator
import json
import re

class QuizGenerateRequest(PydanticBaseModel):
    difficulty: str = "Medium"
    num_questions: int = 5
    document_ids: Optional[List[str]] = None

    @model_validator(mode='before')
    @classmethod
    def check_aliases(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if "documentIds" in values and "document_ids" not in values:
                values["document_ids"] = values["documentIds"]
            if "questionCount" in values and "num_questions" not in values:
                values["num_questions"] = values["questionCount"]
        return values

def clean_json_text(text: str) -> str:
    text = text.strip()
    if "```" in text:
        # Match anything between ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
    return text

@router.post("/generate", response_model=SuccessResponse)
async def generate_quiz_endpoint(
    req: QuizGenerateRequest,
    current_user: UserInDB = Depends(get_current_user)
):
    from app.services.ai.rag_service import rag_service
    from app.services.ai.generator import ai_generator
    from app.repositories.document import document_repo
    from app.services.ai.document_processor import document_processor
    import os, re
    
    doc_ids = req.document_ids if (req.document_ids and len(req.document_ids) > 0) else None
    context_chunks = rag_service.similarity_search(
        "main concepts and topics", 
        user_id=current_user.id, 
        top_k=15, 
        document_ids=doc_ids
    )
    
    doc_name = "Study Material"
    if doc_ids and doc_ids[0]:
        doc = await document_repo.get_by_id(doc_ids[0])
        if doc:
            doc_name = doc.original_name or doc.file_name or "Study Material"
            if not context_chunks and doc.storage_path and os.path.exists(doc.storage_path):
                try:
                    extracted_text = document_processor.extract_text(doc.storage_path, doc.file_type)
                    if extracted_text and len(extracted_text.strip()) > 0:
                        context_chunks = [{"content": extracted_text[:8000], "metadata": {"document_id": doc_ids[0]}}]
                except Exception as e:
                    pass

    clean_topic = re.sub(r'\.[^/.]+$', '', doc_name)
    clean_topic = re.sub(r'[-_]', ' ', clean_topic)
    
    if not context_chunks:
        context_chunks = [{"content": f"Study material for subject: {clean_topic}. Main concepts, definitions, protocols, mechanisms, and key theoretical rules.", "metadata": {"document_id": doc_ids[0] if doc_ids else "General"}}]
        
    raw_response = await ai_generator.generate_quiz(context_chunks, req.difficulty, req.num_questions)
    
    cleaned = clean_json_text(raw_response)
    try:
        data = json.loads(cleaned)
    except Exception as e:
        data = raw_response
        
    return SuccessResponse(message="Quiz generated", data=data)
