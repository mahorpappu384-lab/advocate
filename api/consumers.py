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
    """
    WebSocket for real-time chat inside a ChatRoom.
    Connect: ws://host/ws/chat/<room_id>/
    Headers: Authorization: Bearer <token>   (handled by JWTAuthMiddleware in production)
    """

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group = f"chat_{self.room_id}"
        self.user = self.scope.get('user')

        # Check user is authenticated and is a participant
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        is_participant = await self.check_participant()
        if not is_participant:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Mark user online
        await self.set_online(True)

        # Notify others: user joined / is online
        await self.channel_layer.group_send(self.room_group, {
            "type": "user_status",
            "user_id": str(self.user.id),
            "username": self.user.username,
            "is_online": True,
        })

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group'):
            await self.set_online(False)
            await self.channel_layer.group_send(self.room_group, {
                "type": "user_status",
                "user_id": str(self.user.id),
                "username": self.user.username,
                "is_online": False,
            })
            await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', 'chat_message')

        if msg_type == 'chat_message':
            content = data.get('content', '').strip()
            if not content:
                return
            # Save message to DB
            message = await self.save_message(content, data.get('reply_to'))
            # Broadcast to room
            await self.channel_layer.group_send(self.room_group, {
                "type": "chat_message",
                "message": {
                    "id": str(message.id),
                    "sender_id": str(self.user.id),
                    "sender_name": self.user.full_name,
                    "username": self.user.username,
                    "content": content,
                    "message_type": "text",
                    "reply_to": data.get('reply_to'),
                    "created_at": message.created_at.isoformat(),
                    "is_edited": False,
                }
            })

        elif msg_type == 'typing':
            # Broadcast typing indicator
            await self.channel_layer.group_send(self.room_group, {
                "type": "typing_indicator",
                "user_id": str(self.user.id),
                "username": self.user.username,
                "is_typing": data.get('is_typing', False),
            })

        elif msg_type == 'message_read':
            # Mark messages as read
            await self.mark_messages_read()
            await self.channel_layer.group_send(self.room_group, {
                "type": "messages_read",
                "user_id": str(self.user.id),
                "room_id": self.room_id,
            })

    # ── Event Handlers (group_send → individual socket) ──────────────────────

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "chat_message",
            "message": event["message"],
        }))

    async def typing_indicator(self, event):
        # Don't send typing indicator back to the typer themselves
        if str(self.user.id) != event["user_id"]:
            await self.send(text_data=json.dumps({
                "type": "typing",
                "user_id": event["user_id"],
                "username": event["username"],
                "is_typing": event["is_typing"],
            }))

    async def user_status(self, event):
        await self.send(text_data=json.dumps({
            "type": "user_status",
            "user_id": event["user_id"],
            "username": event["username"],
            "is_online": event["is_online"],
        }))

    async def messages_read(self, event):
        await self.send(text_data=json.dumps({
            "type": "messages_read",
            "user_id": event["user_id"],
            "room_id": event["room_id"],
        }))

    # ── DB Helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def check_participant(self):
        from .models import ChatRoom
        return ChatRoom.objects.filter(
            id=self.room_id,
            room_participants__user=self.user
        ).exists()

    @database_sync_to_async
    def save_message(self, content, reply_to_id=None):
        from .models import Message, ChatRoom
        room = ChatRoom.objects.get(id=self.room_id)
        reply_to = None
        if reply_to_id:
            reply_to = Message.objects.filter(id=reply_to_id).first()
        msg = Message.objects.create(
            room=room,
            sender=self.user,
            message_type='text',
            content=content,
            reply_to=reply_to,
        )
        room.updated_at = timezone.now()
        room.save(update_fields=['updated_at'])
        return msg

    @database_sync_to_async
    def mark_messages_read(self):
        from .models import ChatRoom, Message, MessageReadReceipt, ChatParticipant
        room = ChatRoom.objects.get(id=self.room_id)
        unread = Message.objects.filter(room=room, is_deleted=False).exclude(sender=self.user)
        for msg in unread:
            MessageReadReceipt.objects.get_or_create(message=msg, user=self.user)
        ChatParticipant.objects.filter(room=room, user=self.user).update(
            last_read_at=timezone.now()
        )

    @database_sync_to_async
    def set_online(self, status):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        User.objects.filter(id=self.user.id).update(
            is_online=status,
            last_seen=timezone.now() if not status else None
        )


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