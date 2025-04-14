import os
from datetime import datetime
from azure.storage.blob import BlobServiceClient
import os
import requests
import tempfile
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import ContentFormat
from dotenv import load_dotenv

load_dotenv()


class UploadToBlob:
    def __init__(self):
        self.account_name = "prodpublic24"
        self.account_key = "9uBBrUvKWddmweMD7uNvZb2KjaqYL1xM7I8+2M3tsVBDZZtPlbmm3cVzqIH6ZsjWaZabjVF1NJtS+AStzgxShg=="
        self.container_name = "sebi-circulars"
        self.connection_string = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={self.account_name};"
            f"AccountKey={self.account_key};"
            f"EndpointSuffix=core.windows.net"
        )

    def upload_to_blob(self, file_path: str) -> str:
        """Upload a file to Azure Blob Storage and return its URL"""
        try:
            print(f"Uploading {file_path} to Azure Blob Storage.")
            blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = blob_service_client.get_container_client(self.container_name)

            # Generate unique blob name
            file_name = os.path.basename(file_path)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            blob_name = f"{timestamp}_{file_name}"

            # Get blob client and upload
            blob_client = container_client.get_blob_client(blob_name)
            with open(file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)

            print(f"File uploaded to Blob Storage with URL: {blob_client.url}")
            return blob_client.url

        except Exception as e:
            print(f"Error uploading to blob storage: {e}")
            raise


class PDFContentExtractor:
    def __init__(self):
        self.endpoint = os.getenv("DOC_PROCESSING_ENDPOINT")
        self.key = os.getenv("DOC_PROCESSING_KEY")
        self.client = DocumentIntelligenceClient(endpoint=self.endpoint, credential=AzureKeyCredential(self.key))

    def get_content_from_pdf(self, file_url: str):
        """Extracts content from a PDF file and returns the text and structured content."""
        try:
            response = requests.get(file_url)
            if response.status_code != 200:
                print(f"Failed to download file from {file_url}")
                return None

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name

            with open(temp_file_path, "rb") as f:
                poller = self.client.begin_analyze_document(
                    "prebuilt-layout",
                    analyze_request=f,
                    content_type="application/octet-stream",
                    output_content_format=ContentFormat.MARKDOWN,
                )
                result = poller.result()

            os.unlink(temp_file_path)
            page_content = {}
            for page in result.pages:
                page_number = str(page.page_number)
                content = [line.content for line in page.lines]
                page_content[page_number] = "\n".join(content)

            output_dict = {temp_file_path: page_content}
            full_text = result.get('content', '')
            return full_text, output_dict

        except Exception as e:
            print(f"Error extracting content from PDF: {e}")
            raise


if __name__ == "__main__":
    # upload_helper = UploadToBlob()
    # path = "/Users/abhinav/Documents/ankush/excel_agent/12 CFR Part 302 (up to date as of 1-23-2025).pdf"
    # url = upload_helper.upload_to_blob(path)
    # print(url)
    url = "https://prodpublic24.blob.core.windows.net/sebi-circulars/20250413_185601_12%20CFR%20Part%20302%20%28up%20to%20date%20as%20of%201-23-2025%29.pdf"
    pdf_content_extractor = PDFContentExtractor()
    content, page_wise_content = pdf_content_extractor.get_content_from_pdf(url)
    # print(content)
    chunks = []
    for file_path, pages in page_wise_content.items():
        for page_number, content in pages.items():
            temp = f"this is the page number: {page_number}\n{content}"
            chunks.append(temp)

    for chunk in chunks:
        print(chunk)
        print("--------------------------------")
        print("\n")