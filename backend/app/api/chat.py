"""Chat API — standard JSON endpoint + SSE streaming endpoint."""
import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.schemas import ChatRequest, ChatResponse, BotMessage
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Standard chat endpoint — returns full ChatResponse in one JSON payload."""
    service = ConversationService(db)
    return await service.handle_message(
        customer_id=request.customer_id,
        message=request.message,
        channel=request.channel,
        conversation_id=request.conversation_id,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """SSE streaming endpoint — emits each BotMessage as a separate event.

    Client usage:
        const es = new EventSource('/chat/stream');  // or use fetch + ReadableStream
    Each event is a JSON object: {"type": "text"|"buttons"|"done", "text": "...", ...}
    """
    service = ConversationService(db)

    async def event_generator():
        try:
            response = await service.handle_message(
                customer_id=request.customer_id,
                message=request.message,
                channel=request.channel,
                conversation_id=request.conversation_id,
            )
            for msg in response.messages:
                payload = json.dumps({
                    "type": msg.type,
                    "text": msg.text,
                    "buttons": msg.buttons,
                    "state": response.state,
                    "conversation_id": response.conversation_id,
                }, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0)  # yield control between messages
            # Terminal done event
            yield f"data: {json.dumps({'type': 'done', 'state': response.state, 'conversation_id': response.conversation_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': 'An unexpected error occurred. Please try again.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversation/{conversation_id}")
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    """Retrieve conversation state and event history."""
    from app.models.db_models import Conversation, ConversationEvent
    from fastapi import HTTPException
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    events = (
        db.query(ConversationEvent)
        .filter(ConversationEvent.conversation_id == conversation_id)
        .order_by(ConversationEvent.created_at)
        .all()
    )
    return {
        "conversation": {
            "id": conv.id,
            "customer_id": conv.customer_id,
            "status": conv.status,
            "current_step_id": conv.current_step_id,
            "sop_flow_id": conv.sop_flow_id,
        },
        "events": [
            {
                "type": e.event_type,
                "user_message": e.user_message,
                "bot_message": e.bot_message,
                "step": e.current_step_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
