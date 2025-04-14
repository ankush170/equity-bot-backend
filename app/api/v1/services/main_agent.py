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

 
def create_agent(web_search: bool = False, document_search: bool = False, document_user_id: Optional[str] = None):
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
            # Instead of trying to configure the tool, we'll use the original tool
            # and handle the user_id in the tool's implementation
            tools = [qdrant_search_tool]
            
            # Add the user_id to the system prompt so the agent knows to use it
            if document_user_id:
                system_prompt += f"\n\nWhen using the qdrant_search_tool, always pass the user_id parameter with the value '{document_user_id}'."
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
    first_response_started = False  # Flag to track first real response chunk

    print("\n=== Starting New Agent Run ===")
    print(f"Query: {query}")
    if conversation_history:
        print(f"Conversation History Length: {len(conversation_history)}")

    # Format conversation history for the agent
    formatted_prompt = query
    if conversation_history and len(conversation_history) > 1:  # Only include if there's actual history
        formatted_prompt = "Previous conversation:\n"
        for msg in conversation_history[:-1]:  # Exclude the current query
            role = "User" if msg["role"] == "user" else "Assistant"
            formatted_prompt += f"{role}: {msg['content']}\n"
        formatted_prompt += f"\nCurrent query: {query}"
        print("\nFormatted Prompt:")
        print(formatted_prompt)

    async with agent.iter(user_prompt=formatted_prompt) as run:
        async for node in run:
            print(f"\nNode Type: {type(node).__name__}")
            
            if Agent.is_model_request_node(node):
                print("Processing Model Request Node")
                initial_buffer = ""  # Buffer specifically for initial response
                
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, TextPartDelta):
                                content = event.delta.content_delta
                                print(f"Content Delta: {content}", end='', flush=True)
                                
                                if not first_response_started:
                                    # Accumulate initial content until we have enough to identify a proper sentence start
                                    initial_buffer += content
                                    
                                    # Wait until we have enough content to ensure we've captured the start of the sentence
                                    if len(initial_buffer) >= 15 or "." in initial_buffer or "!" in initial_buffer or "?" in initial_buffer:
                                        # Fix common truncation issues with the first character
                                        
                                        # Common starting word repairs
                                        if initial_buffer.startswith(" apologize") or initial_buffer.startswith("apologize"):
                                            initial_buffer = "I " + initial_buffer.lstrip()
                                        elif initial_buffer.startswith(" am") or initial_buffer.startswith("am "):
                                            initial_buffer = "I" + initial_buffer
                                        elif initial_buffer.startswith("'d ") or initial_buffer.startswith("d "):
                                            initial_buffer = "I" + initial_buffer.replace("d ", "'d ")
                                        elif initial_buffer.startswith("'ll ") or initial_buffer.startswith("ll "):
                                            initial_buffer = "I" + initial_buffer.replace("ll ", "'ll ")
                                        elif initial_buffer.startswith("'m ") or initial_buffer.startswith("m "):
                                            initial_buffer = "I" + initial_buffer.replace("m ", "'m ")
                                        elif initial_buffer.startswith(" can") or initial_buffer.startswith("can "):
                                            initial_buffer = "I" + initial_buffer
                                        elif initial_buffer.startswith(" will") or initial_buffer.startswith("will "):
                                            initial_buffer = "I" + initial_buffer
                                        # Fix missing 'T' in "The"  
                                        elif initial_buffer.startswith("he ") and len(initial_buffer) < 25:
                                            initial_buffer = "T" + initial_buffer
                                        # Fix missing 'L' in "Let"
                                        elif initial_buffer.startswith("et ") and len(initial_buffer) < 25:
                                            initial_buffer = "L" + initial_buffer
                                        # General case - if it starts with a space, assume it needs "I" prefix
                                        elif initial_buffer.strip() and initial_buffer.startswith(" ") and len(initial_buffer) < 25:
                                            initial_buffer = "I" + initial_buffer
                                        
                                        current_text = initial_buffer
                                        print(f"\nFirst Response Started: {initial_buffer}")
                                        
                                        yield AgentResponse(
                                            response=current_text,
                                            delta=initial_buffer
                                        )
                                        
                                        first_response_started = True
                                        initial_buffer = ""  # Clear the initial buffer
                                else:
                                    # Handle normal streaming after the first chunk is processed
                                    buffer += content
                                    
                                    # If buffer contains complete words or punctuation, yield it
                                    if buffer.endswith((' ', '.', '!', '?', '\n', ',', ':', '-', ';')):
                                        current_text += buffer
                                        print(f"\nYielding Buffer: {buffer}")
                                        yield AgentResponse(
                                            response=current_text,
                                            delta=buffer
                                        )
                                        buffer = ""  # Clear the buffer after yielding

            elif Agent.is_end_node(node):
                print("\nReached End Node")
                # Yield any remaining content in buffer or initial buffer
                if buffer:
                    current_text += buffer
                    print(f"Final Buffer Content: {buffer}")
                    yield AgentResponse(
                        response=current_text,
                        delta=buffer
                    )
                
                # Signal completion
                print("\n=== Agent Run Complete ===")
                print(f"Final Response Length: {len(current_text)}")
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