import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent, Tool
from pydantic_ai.models.bedrock import BedrockConverseModel  
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.result import FinalResult
from app.tools.web_search import web_search_tool
from app.tools.document_search import qdrant_search_tool

import os
import logging

from dotenv import load_dotenv
load_dotenv()
# Import necessary event classes
from pydantic_ai.messages import (
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ToolCallPartDelta,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AgentResponse(BaseModel):
    """Model for agent responses"""
    response: str = Field(..., description="The agent's response to the query")
    thoughts: Optional[List[Dict[str, Any]]] = Field(None, description="The agent's thought process")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tools called during processing")
    delta: Optional[str] = Field(None, description="The delta of the response")

 
def create_agent(web_search: bool = False, document_search: bool = False):
    """Create and configure the AI agent with tools"""
    try:
        # Create the Bedrock provider with AWS credentials
        bedrock_provider = BedrockProvider(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION_NAME", "us-east-1")
        )
        # Create the Anthropic model with Bedrock provider
        try:
            model = BedrockConverseModel(
                model_name=os.getenv("LLM_MODEL"),  
                provider=bedrock_provider
            )
        except Exception as e:
            print("this is the error", e)

        # Define system prompt based on web_search capability
        if web_search:
            system_prompt = """ 
                You are an expert financial analyst. You are given a question regarding financial data,
                you need to use the web search tool, write good web queries and find the data, and return it in a structured format.
                
                When responding to queries, consider the conversation history provided to maintain context.
                If previous messages contain relevant information, use it to provide more accurate and contextual responses.
                However, ensure each response can stand on its own while being contextually aware.
                
                You can't ask for clarifications, you need to understand the question and answer it yourself.
                Please cite the website source of the information you provide.
                """
            tools = [web_search_tool]
        elif document_search:
            system_prompt = """
                You are an expert financial analyst engaging in a conversation about financial topics.
                Your role is to provide clear, accurate, and helpful responses based on your existing knowledge.
                
                When responding to queries, consider the conversation history provided to maintain context.
                If previous messages contain relevant information, use it to provide more accurate and contextual responses.
                However, ensure each response can stand on its own while being contextually aware.
                
                You can't ask for clarifications, you need to understand the question and answer it yourself.
                Note that you don't have access to real-time data or web search, so focus on providing general financial analysis, 
                explanations, and insights based on your training data.

                You can use the qdrant search tool to search for information in the documents, that the user has uploaded
                give clarifications from the document itself, dont give your own interpretations. only answer from the document.
                please cite the page number from where you got the information.
                """
            tools = [qdrant_search_tool]  # No tools when web_search is disabled
        else:
            system_prompt = """
                You are an expert financial analyst engaging in a conversation about financial topics.
                Your role is to provide clear, accurate, and helpful responses based on your existing knowledge.
            """
            tools = []

        # Create the agent with the model and appropriate tools
        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt
        )
        print("agent created successfully")
        return agent
    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}")
        raise


async def run_agent(agent: Agent, query: str, max_iterations: int = 5) -> AgentResponse:
    """Run the agent with the provided query and log all intermediate steps"""
    try:
        tool_calls = []
        thoughts = []
        response_parts = []
        async with agent.iter(user_prompt=query) as agent_run:
            async for node in agent_run:
                # Handle model response parts
                if hasattr(node, 'model_response') and hasattr(node.model_response, 'parts'):
                    for part in node.model_response.parts:
                        if part.part_kind == 'text':
                            response_parts.append(part.content)
                        elif part.part_kind == 'tool-call':
                            tool_name = part.tool_name
                            args = part.args_as_dict() if hasattr(part, 'args_as_dict') else part.args
                            tool_calls.append({
                                "tool": tool_name,
                                "input": args,
                                "output": None
                            })

                            thoughts.append({
                                "thought": f"I need to use {tool_name} to find information",
                                "action": tool_name,
                                "action_input": args
                            })

                if hasattr(node, 'request') and hasattr(node.request, 'parts'):
                    for part in node.request.parts:
                        part_kind = getattr(part, 'part_kind', None)
                        if part_kind == 'tool-return':
                            tool_name = part.tool_name
                            content = part.content

                            for tc in tool_calls:
                                if tc["tool"] == tool_name and tc["output"] is None:
                                    tc["output"] = content
                                    break
                
                print("\n\n\n")
                if type(node).__name__ == 'End' and hasattr(node, 'data'):
                    if hasattr(node.data, 'data'):
                        final_text = node.data.data
                        response_parts.append(final_text)
                        print("this is the final text", final_text)
                    else:
                        final_text = str(node.data)
                        response_parts.append(final_text)
                        print("this is the final text", final_text)


        complete_response = "\n".join(response_parts)
        # print("\n======= Final Aggregated Response =======")
        # print(complete_response)

        return AgentResponse(
            response=complete_response,
            thoughts=thoughts if thoughts else None,
            tool_calls=tool_calls if tool_calls else None
        )

    except Exception as e:
        logger.error(f"Error running agent: {str(e)}")
        raise
        



async def run_agent_with_streaming(agent: Agent, query: str, conversation_history: List[Dict[str, str]] = None, max_iterations: int = 5):
    """Run the agent with the provided query and stream its internal processing events."""
    current_text = ""
    buffer = ""  # Add a buffer to handle partial words/characters
    first_chunk = True  # Flag to handle the first chunk differently

    # Format conversation history for the agent
    formatted_prompt = query
    if conversation_history and len(conversation_history) > 1:  # Only include if there's actual history
        formatted_prompt = "Previous conversation:\n"
        for msg in conversation_history[:-1]:  # Exclude the current query
            role = "User" if msg["role"] == "user" else "Assistant"
            formatted_prompt += f"{role}: {msg['content']}\n"
        formatted_prompt += f"\nCurrent query: {query}"

    async with agent.iter(user_prompt=formatted_prompt) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, TextPartDelta):
                                content = event.delta.content_delta
                                
                                # Handle first chunk immediately
                                if first_chunk and content.strip():
                                    first_chunk = False
                                    current_text += content
                                    yield AgentResponse(
                                        response=current_text,
                                        delta=content
                                    )
                                    continue

                                # Add new content to buffer
                                buffer += content
                                
                                # If buffer contains complete words or punctuation, yield it
                                if buffer.endswith((' ', '.', '!', '?', '\n', ',', ':', '-', ';')):
                                    current_text += buffer
                                    yield AgentResponse(
                                        response=current_text,
                                        delta=buffer
                                    )
                                    buffer = ""  # Clear the buffer after yielding

            elif Agent.is_end_node(node):
                # Yield any remaining content in buffer
                if buffer:
                    current_text += buffer
                    yield AgentResponse(
                        response=current_text,
                        delta=buffer
                    )
                
                # Signal completion
                yield AgentResponse(
                    response=current_text,
                    delta=""  # Empty delta signals completion
                )

# Example main to run and stream the thoughts.
if __name__ == "__main__":
    async def main():
        agent = create_agent()  
        query = "How did zomato perform in the latest financial year?"
        async for response in run_agent_with_streaming(agent, query):
            print("\n=== Final Aggregated Response ===")
            print(response.response)

            print("\n=== Streaming Thoughts ===")
            if response.thoughts:
                for t in response.thoughts:
                    print(t)

    asyncio.run(main())