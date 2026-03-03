import base64
import os
import uuid
from datetime import datetime, timezone
from azure.storage.queue import QueueClient

class AzuriteQueueManager:
    def __init__(self, connection_string: str = None):
        """Initialize the queue manager with Azurite connection string."""
        self.connection_string = connection_string or os.getenv(
            "AzureWebJobsStorage",
            "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
        )

    def create_queue(self, queue_name: str) -> QueueClient:
        """Create a queue and return the client."""
        client = QueueClient.from_connection_string(
            self.connection_string, queue_name=queue_name
        )
        client.create_queue()
        return client

    def get_queue_client(self, queue_name: str) -> QueueClient:
        """Get an existing queue client."""
        return QueueClient.from_connection_string(
            self.connection_string, queue_name=queue_name
        )

    def send_message(self, queue_name: str, message: str) -> str:
        """Send a message to a queue."""
        client = self.get_queue_client(queue_name)
        response = client.send_message(message)
        return response.id

    def receive_messages(self, queue_name: str, max_messages: int = 1):
        """Receive messages from a queue."""
        client = self.get_queue_client(queue_name)
        return client.receive_messages(max_messages=max_messages)

    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str):
        """Delete a message from a queue."""
        client = self.get_queue_client(queue_name)
        client.delete_message(message_id, pop_receipt)

    def delete_queue(self, queue_name: str):
        """Delete a queue."""
        client = self.get_queue_client(queue_name)
        client.delete_queue()