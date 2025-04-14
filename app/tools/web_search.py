from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import os
import logging
import httpx
from pydantic_ai import Tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebSearchResult(BaseModel):
    """Model for web search results"""
    title: str = Field(..., description="Title of the search result")
    link: str = Field(..., description="URL of the search result")
    snippet: str = Field(..., description="Snippet/description of the search result")

class WebSearchResponse(BaseModel):
    """Model for web search response"""
    results: List[WebSearchResult] = Field(..., description="List of search results")
    total_results: Optional[int] = Field(None, description="Total number of results found")

@Tool
async def web_search_tool(
    query: str = Field(..., description="The search query to execute"),
    num_results: int = Field(5, description="Number of results to return")
) -> WebSearchResponse:
    """
    Searches the web for information based on the provided query.
    
    This tool uses a search API to find relevant information on the web.
    It returns a structured list of search results including titles, complete links including https://, and snippets.
    
    Args:
        query: The search query to execute
        num_results: Number of results to return (default: 5)
        
    Returns:
        A WebSearchResponse object containing the search results
    """
    search_api_key = os.getenv("SEARCH_API_KEY")
    if not search_api_key:
        logger.error("SEARCH_API_KEY environment variable not set")
        raise ValueError("Search API key not configured. Please set the SEARCH_API_KEY environment variable.")
    
    # Extract actual values from the parameters
    query_value = query.default if hasattr(query, 'default') else query
    num_results_value = num_results.default if hasattr(num_results, 'default') else num_results

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "query": query_value,
                    "max_results": num_results_value,
                    "api_key": search_api_key
                },
                timeout=10.0
            )
            
            if response.status_code != 200:
                logger.error(f"Tavily API returned error: {response.status_code} - {response.text}")
                raise ValueError(f"Tavily API error: {response.status_code}")
            
            data = response.json()
            
            results = [
                WebSearchResult(
                    title=result.get("title", "No title"),
                    link=result.get("url", ""),
                    snippet=result.get("content", "No description")
                )
                for result in data.get("results", [])
            ]
        
            web_search_response = WebSearchResponse(
                results=results,
                total_results=num_results_value
            )
            return web_search_response
            
    except Exception as e:
        logger.error(f"Error during web search: {str(e)}")
        mock_results = [
            WebSearchResult(
                title="Mock search result 1",
                link="https://example.com/result1",
                snippet="This is a mock search result for demonstration purposes."
            ),
            WebSearchResult(
                title="Mock search result 2",
                link="https://example.com/result2",
                snippet="Another mock result since the actual API call failed."
            )
        ]
        return WebSearchResponse(results=mock_results, total_results=2)