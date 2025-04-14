from qdrant_client import QdrantClient
from qdrant_client.http import models
import os
from openai import AzureOpenAI
from dotenv import load_dotenv
import uuid
import logging
load_dotenv()

logger = logging.getLogger(__name__)

def create_qdrant_collection(client, collection_name, index_fields):
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE)
        )
        for field, schema_type in index_fields.items():
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=schema_type
            )
        print(f"Created collection {collection_name} with payload indices: {list(index_fields.keys())}")
    else:
        print(f"Collection {collection_name} already exists")

def generate_vector(query: str) -> list:
    oai_client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        api_key=os.getenv("AZURE_KEY")
    )
    if not oai_client:
        logger.error("OpenAI client not initialized")
        raise ValueError("OpenAI client not initialized")
    print("this is the oai client", oai_client)
    try:
        if not query or not isinstance(query, str):
            logger.warning("Invalid input for vector generation")
            return [0.0] * 1536
            
        formatted_input = query.strip()[:8000]
        
        if not formatted_input:
            logger.warning("Empty string after stripping whitespace - cannot generate embeddings")
            return [0.0] * 1536
            
        response = oai_client.embeddings.create(
            input=[formatted_input],
            model=os.getenv("AZURE_EMBEDDING_MODEL")
        )
        
        return response.data[0].embedding
        
    except Exception as e:
        logger.error(f"Error generating vector: {str(e)}")
        return [0.0] * 1536

def write_to_qdrant(qdrant_client, obj_id, collection_name, chunks, metadata=None):
    vectors = [generate_vector(chunk) for chunk in chunks]    
    
    base_payload = {
        "object_id": str(obj_id),
    }
    
    if metadata:
        base_payload.update(metadata)
    
    points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                **base_payload,
                "chunk": chunk
            }
        )
        for idx, (vector, chunk) in enumerate(zip(vectors, chunks))
    ]
    qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )

def get_collection_name(class_name) -> str:
    """Convert class name to snake case for collection name"""
    snake_case = class_name[0].lower()
    for char in class_name[1:]:
        if char.isupper():
            snake_case += '_' + char.lower()
        else:
            snake_case += char
    collection_name = "os_" + snake_case
    print(f"Collection name for Qdrant: {collection_name}")  # Debug print
    return collection_name

def search_qdrant_with_filters(qdrant_client, collection_name, query_vector, filters=None, limit=5):
    try:
        print(f"Starting Qdrant search in collection: {collection_name}")
        print(f"Using filters: {filters}")
        
        if filters is not None and not isinstance(filters, dict):
            logger.warning(f"Invalid filters type: expected dict, got {type(filters)}. Proceeding without filters.")
            filters = None
            
        if filters:
            filter_conditions = []
            
            for key, value in filters.items():
                print(f"Adding filter condition: {key}={value}")
                filter_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=str(value))
                    )
                )
            
            if filter_conditions:
                search_filter = models.Filter(
                    must=filter_conditions
                )
                
                print(f"Executing search with filter conditions: {filter_conditions}")
                results = qdrant_client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    query_filter=search_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=True
                )
                print(f"Search returned {len(results)} results")
                return results
        
        print("Executing search without filters")
        results = qdrant_client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=True
        )
        print(f"Search returned {len(results)} results")
        return results
    except Exception as e:
        logger.error(f"Error searching Qdrant with filters: {str(e)}")
        return []






