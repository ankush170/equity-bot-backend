from mongoengine import DynamicDocument, StringField, ListField, EmbeddedDocument, EmbeddedDocumentListField, ReferenceField, IntField, FloatField, BooleanField, DateTimeField
from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.api.v1.services.qdrant_utils import write_to_qdrant, generate_vector, get_collection_name, create_qdrant_collection, search_qdrant_with_filters
import uuid
import os
from datetime import datetime
import asyncio
from app.api.v1.services.upload_helper import UploadToBlob, PDFContentExtractor

# Initialize client asynchronously
qdrant_client = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY")
    )

if not qdrant_client:
    print("Qdrant client ❌")
else:
    print("Qdrant client ✅")

processing_status = ["processing", "completed", "failed"]


class User(DynamicDocument):
    name = StringField(required=True)
    email = StringField(required=True)
    password = StringField(required=True)
    created_at = DateTimeField(default=datetime.now)


class Document(DynamicDocument):
    file_name = StringField(required=True)
    url = StringField(required=True)
    uploaded_at = DateTimeField(default=datetime.now)
    user = ReferenceField(User, required=True)
    processing_status = StringField(required=True)


class Message(DynamicDocument):
    user = ReferenceField(User, required=True)
    user_query = StringField(required=True)
    agent_response = StringField(required=True)
    created_at = DateTimeField(default=datetime.now)



class Thread(DynamicDocument):
    user = ReferenceField(User, required=True)
    messages = ListField(ReferenceField(Message))
    created_at = DateTimeField(default=datetime.now)
    meta = {"index": ["user"]}

class CustomDocument(DynamicDocument):
    user = ReferenceField(User, required=True)
    file_name = StringField(required=True)
    url = StringField(required=True)
    uploaded_at = DateTimeField(default=datetime.now)
    processing_status = StringField(required=True, choices=processing_status)
    starting_content = StringField(required=True)

    def create_semantic_chunks(self, page_wise_content):
        # Chunk the content into meaningful parts using a page-wise strategy
        chunks = []
        for file_path, pages in page_wise_content.items():
            for page_number, content in pages.items():
                temp = f"this is the page number: {page_number}\n{content}"
                chunks.append(temp)
        return chunks

    def save(self, update_qdrant=False, url=None, *args, **kwargs):
        if not url:
            raise ValueError("Url is required for processing")
        
        try:
            pdf_content_extractor = PDFContentExtractor()
            content, page_wise_content = pdf_content_extractor.get_content_from_pdf(url)
            self.starting_content = content[:1000]
            
            # Save to MongoDB first
            super().save(*args, **kwargs)
            
            if update_qdrant:
                try:
                    qdrant_collection_name = get_collection_name(self.__class__.__name__)
                    print(f"Saving to Qdrant collection: {qdrant_collection_name}")
                    
                    # Debug prints for document data
                    print(f"Document ID: {self.id}")
                    print(f"User ID: {self.user.id}")
                    print(f"File name: {self.file_name}")
                    
                    chunks = self.create_semantic_chunks(page_wise_content)
                    print(f"Created {len(chunks)} chunks")
                    print(f"First chunk sample: {chunks[0][:200] if chunks else 'No chunks created'}")
                    
                    metadata = {
                        "user_id": str(self.user.id),
                        "file_name": self.file_name
                    }
                    print(f"Metadata: {metadata}")
                    
                    write_to_qdrant(
                        qdrant_client, 
                        str(self.id),
                        qdrant_collection_name, 
                        chunks, 
                        metadata
                    )
                    
                    self.processing_status = "completed"
                    super().save()
                    
                except Exception as e:
                    print(f"Error saving to Qdrant: {e}")
                    self.processing_status = "failed"
                    super().save()
                    raise
                
            return self
            
        except Exception as e:
            print(f"Error in save method: {e}")
            self.processing_status = "failed"
            super().save()
            raise

    @classmethod
    def search(cls, query, filters=None, limit=5):
        try:
            qdrant_collection_name = get_collection_name(cls.__name__)
            print(f"Searching in Qdrant collection: {qdrant_collection_name}")
            print(f"Search filters: {filters}")
            
            search_vector = generate_vector(query)
            
            # Add debug print for search parameters
            print(f"Search parameters:")
            print(f"- Collection: {qdrant_collection_name}")
            print(f"- Query: {query}")
            print(f"- Filters: {filters}")
            print(f"- Limit: {limit}")
            
            search_results = search_qdrant_with_filters(
                qdrant_client=qdrant_client,
                collection_name=qdrant_collection_name,
                query_vector=search_vector,
                filters=filters,
                limit=limit
            )
            
            # Add debug print for raw results
            print(f"Raw search results: {search_results}")
            
            result_dict = {
                result.payload.get("object_id"): result.payload.get("chunk", "")
                for result in search_results 
                if result.payload.get("object_id") and result.payload.get("chunk")
            }
            
            print(f"Found {len(result_dict)} results")
            print(f"Result payloads: {result_dict}")
            return result_dict
            
        except Exception as e:
            print(f"Error searching Qdrant: {e}")
            return {}

    def delete(self, *args, **kwargs):
        try:           
            super().delete(*args, **kwargs)
            print(f"Workbook with id {self.id} deleted from mongodb")
        except Exception as e:
            print(f"Error deleting from mongodb: {e}")
            raise
        try:
            stable_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(self.id)))
            
            qdrant_client.delete(
                collection_name=get_collection_name(self.__class__.__name__),
                points_selector=models.PointIdsList(points=[stable_uuid])
            )
            
            print(f"Workbook with id {self.id} deleted from Qdrant: {stable_uuid}")
        except Exception as e:
            print(f"Error deleting from Qdrant: {e}")
            raise






