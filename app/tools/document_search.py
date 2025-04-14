from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import os
import logging
import httpx
from pydantic_ai import Tool
from app.models.models import CustomDocument
import asyncio
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QdrantSearchResult(BaseModel):
    """Model for qdrant search results"""
    text: str = Field(..., description="Text of the search result")

class QdrantSearchResponse(BaseModel):
    """Model for qdrant search response"""
    results: List[QdrantSearchResult] = Field(..., description="List of search results")
    total_results: Optional[int] = Field(None, description="Total number of results found")

@Tool
async def qdrant_search_tool(
    query: str = Field(..., description="The search query to execute"),
    num_results: int = Field(5, description="Number of results to return"),
    user_id: str = Field(..., description="User ID for filtering results")
) -> QdrantSearchResponse:
    """
    Searches the qdrant for information based on the provided query.
    
    This tool uses a search API to find relevant information in the documents.
    It returns a structured list of search results including content from the documents.
    
    Args:
        query: The search query to execute
        num_results: Number of results to return (default: 5)
        user_id: User ID for filtering results
        
    Returns:
        A QdrantSearchResponse object containing the search results
    """
    try:
        print(f"Search query: {query}")
        print(f"User ID for filter: {user_id}")
        
        # Use the user_id for filtering
        results = CustomDocument.search(
            query=query,
            filters={"user_id": user_id} if user_id else None,
            limit=num_results
        )
        
        print(f"Number of results: {len(results)}")
        
        # Create a list of QdrantSearchResult from the results
        search_results = [
            QdrantSearchResult(text=result) for result in results.values()
        ]
        
        return QdrantSearchResponse(
            results=search_results, 
            total_results=len(search_results)
        )
        
    except Exception as e:
        logger.error(f"Error during document search: {str(e)}")
        # Return empty results instead of mock data
        return QdrantSearchResponse(results=[], total_results=0)

if __name__ == "__main__":
    ans = asyncio.run(qdrant_search_tool("What is the capital of India?", 5, "user123"))
    print(ans)