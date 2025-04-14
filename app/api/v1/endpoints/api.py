from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio
from mongoengine import connect
import os
from dotenv import load_dotenv

from app.api.v1.services.main_agent import create_agent, run_agent_with_streaming
from app.models.models import User, Thread, Message, CustomDocument
from app.api.v1.services.auth_utils import get_current_user

# Load environment variables
load_dotenv()

# Connect to MongoDB
connect(db=os.getenv("MONGO_DB"), host=os.getenv("MONGO_URI"))

# Create router instead of app
router = APIRouter()

class FileUploadRequest(BaseModel):
    blob_url: str
    file_name: str

class ChatRequest(BaseModel):
    user_id: str
    query: str
    thread_id: Optional[str] = None
    web_search: bool = False
    document_id: Optional[str] = None

class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str

class StreamingEvent(BaseModel):
    event: str
    data: Dict[str, Any]

class StreamResponse(BaseModel):
    """Model for streaming response data"""
    type: str = Field(..., description="Type of the response (thread_id, content, or done)")
    content: str = Field(..., description="The content of the response")

async def stream_agent_response(user_id: str, query: str, thread_id: Optional[str] = None, web_search: bool = False, use_document_search: bool = False):
    """Stream the agent's response and save to database"""
    try:
        # Create agent
        agent = create_agent(web_search, document_search=use_document_search)
        
        # Get or create user
        user = User.objects(id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get existing thread or create new one
        thread = None
        if thread_id:
            thread = Thread.objects(id=thread_id, user=user).first()
            if not thread:
                raise HTTPException(status_code=404, detail="Thread not found")
        
        if not thread:
            thread = Thread(user=user, messages=[]).save()
        
        # Get conversation history (last 2 messages if they exist)
        conversation_history = []
        if thread.messages:
            last_messages = thread.messages[-2:] if len(thread.messages) > 1 else thread.messages
            for msg in last_messages:
                conversation_history.extend([
                    {"role": "user", "content": msg.user_query},
                    {"role": "assistant", "content": msg.agent_response}
                ])
        
        # Add current query
        conversation_history.append({"role": "user", "content": query})
        
        # Create initial message
        message = Message(
            user=user,
            user_query=query,
            agent_response="",  # Will be updated as we stream
            created_at=datetime.now()
        ).save()
        
        # Add message to thread
        thread.messages.append(message)
        thread.save()

        # Stream agent response with conversation history
        async def generate_events():
            try:
                # First, send the thread ID
                thread_info = StreamResponse(type="thread_id", content=str(thread.id))
                yield f"data: {thread_info.json()}\n\n"
                
                full_response = ""
                async for partial_response in run_agent_with_streaming(agent, query, conversation_history=conversation_history):
                    if partial_response.delta:  # Only yield if there's new content
                        full_response += partial_response.delta
                        content_response = StreamResponse(type="content", content=partial_response.delta)
                        yield f"data: {content_response.json()}\n\n"
                    else:  # Empty delta signals completion
                        # Update message with complete response
                        message.agent_response = full_response
                        message.save()
                        
                        # Signal end of stream
                        done_response = StreamResponse(type="done", content="")
                        yield f"data: {done_response.json()}\n\n"
                
            except Exception as e:
                error_msg = f"Error processing request: {str(e)}"
                error_response = StreamResponse(type="error", content=error_msg)
                yield f"data: {error_response.json()}\n\n"
                done_response = StreamResponse(type="done", content="")
                yield f"data: {done_response.json()}\n\n"

        return StreamingResponse(
            generate_events(),
            media_type="text/event-stream"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/upload")
async def upload_document(
    request: FileUploadRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Upload a document and process it
    """
    try:
        # Create new document
        document = CustomDocument(
            user=current_user,
            file_name=request.file_name,
            url=request.blob_url,
            processing_status="processing"
        )
        
        # Save document with Qdrant processing
        document = document.save(update_qdrant=True, url=request.blob_url)
        
        return {
            "id": str(document.id),
            "file_name": document.file_name,
            "url": document.url,
            "processing_status": document.processing_status,
            "message": "Document uploaded successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Endpoint to chat with the agent and get streaming responses
    """
    try:
        # If document_id is provided, use document search instead of web search
        use_document_search = False
        if request.document_id:
            # Verify document exists and belongs to user
            document = CustomDocument.objects(id=request.document_id, user=request.user_id).first()
            if not document:
                raise HTTPException(status_code=404, detail="Document not found or access denied")
            use_document_search = True
            request.web_search = False  # Disable web search when using document search
        
        return await stream_agent_response(
            request.user_id, 
            request.query, 
            request.thread_id,
            request.web_search,
            use_document_search
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/threads")
async def get_user_threads(current_user: User = Depends(get_current_user)):
    """
    Get all chat threads for the authenticated user
    """
    try:
        threads = Thread.objects(user=current_user).order_by("-created_at")
        return {
            "threads": [{
                "id": str(thread.id),
                "created_at": thread.created_at,
                "first_message": thread.messages[0].user_query if thread.messages else None,
                "message_count": len(thread.messages)
            } for thread in threads]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific thread with all its messages
    """
    try:
        thread = Thread.objects(id=thread_id, user=current_user).first()
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )
            
        return {
            "thread": {
                "id": str(thread.id),
                "created_at": thread.created_at,
                "messages": [{
                    "id": str(msg.id),
                    "user_query": msg.user_query,
                    "agent_response": msg.agent_response,
                    "created_at": msg.created_at
                } for msg in thread.messages]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users")
async def create_user(request: CreateUserRequest):
    """
    Create a new user
    """
    try:
        # Check if user with email already exists
        existing_user = User.objects(email=request.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User with this email already exists")
            
        # Create new user
        user = User(
            name=request.name,
            email=request.email,
            password=request.password  # In a real app, you should hash this password
        ).save()
        
        return {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "created_at": user.created_at
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents")
async def get_user_documents(current_user: User = Depends(get_current_user)):
    """
    Get all documents uploaded by the authenticated user
    """
    try:
        documents = CustomDocument.objects(user=current_user).order_by("-uploaded_at")
        return {
            "documents": [{
                "id": str(doc.id),
                "file_name": doc.file_name,
                "url": doc.url,
                "uploaded_at": doc.uploaded_at,
                "processing_status": doc.processing_status
            } for doc in documents]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 