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
    Connect: wss://host/ws/chat/<room_id>/?token=<jwt_token>
    """

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group = f"chat_{self.room_id}"

        # Get user from scope (middleware) or from query token
        self.user = self.scope.get('user')

        # If middleware didn't authenticate, try manual token from query string
        if not self.user or not self.user.is_authenticated:
            token = self._get_token_from_query()
            if token:
                self.user = await self._get_user_from_token(token)

        if not self.user or not self.user.is_authenticated:
            logger.warning(f"WebSocket auth failed for room {self.room_id}")
            await self.close(code=4001)
            return

        is_participant = await self.check_participant()
        if not is_participant:
            logger.warning(f"User {self.user.id} is not participant in room {self.room_id}")
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Mark user online
        await self.set_online(True)

        # Notify others
        await self.channel_layer.group_send(self.room_group, {
            "type": "user_status",
            "user_id": str(self.user.id),
            "username": self.user.username,
            "is_online": True,
        })

    def _get_token_from_query(self):
        """Extract token from query string: ?token=xxx"""
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        if 'token=' in query_string:
            token_part = query_string.split('token=')[1]
            return token_part.split('&')[0]
        return None

    @database_sync_to_async
    def _get_user_from_token(self, token):
        """Manually decode JWT token and get user"""
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from django.contrib.auth import get_user_model
            User = get_user_model()

            validated_token = AccessToken(token)
            user_id = validated_token['user_id']
            return User.objects.get(id=user_id)
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return None

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
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', 'chat_message')

        if msg_type == 'chat_message':
            content = data.get('content', '').strip()
            if not content:
                return
            message = await self.save_message(content, data.get('reply_to'))
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
            await self.channel_layer.group_send(self.room_group, {
                "type": "typing_indicator",
                "user_id": str(self.user.id),
                "username": self.user.username,
                "is_typing": data.get('is_typing', False),
            })

        elif msg_type == 'message_read':
            await self.mark_messages_read()
            await self.channel_layer.group_send(self.room_group, {
                "type": "messages_read",
                "user_id": str(self.user.id),
                "room_id": self.room_id,
            })

    # ── Event Handlers ──────────────────────────────────────────────────────

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "chat_message",
            "message": event["message"],
        }))

    async def typing_indicator(self, event):
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
        pass

    async def send_notification(self, event):
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": event["notification"],
        }))