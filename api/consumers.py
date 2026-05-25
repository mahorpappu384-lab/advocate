"""
Django Channels WebSocket Consumers.
- ChatConsumer    : Real-time messaging (WhatsApp style)
- NotificationConsumer : Real-time notification push
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        await self.send(text_data=text_data)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket for real-time notification push.
    Connect: ws://host/ws/notifications/
    """

    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.group_name = f"notifications_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Client can send ping
        pass

    async def send_notification(self, event):
        """Receive from channel layer, forward to WebSocket client."""
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": event["notification"],
        }))