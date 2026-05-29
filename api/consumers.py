import json
import logging
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = None
        self.room_id = self.scope['url_route']['kwargs'].get('room_id')
        self.room_group = f"chat_{self.room_id}"

        try:
            scope_user = self.scope.get("user")

            if scope_user and scope_user.is_authenticated:
                self.user = scope_user
            else:
                token = self.get_token_from_query()
                if token:
                    self.user = await self.get_user_from_token(token)

            if not self.user or not self.user.is_authenticated:
                logger.warning("WebSocket authentication failed")
                await self.close(code=4001)
                return

            room_exists = await self.room_exists()
            if not room_exists:
                logger.warning(f"Room not found: {self.room_id}")
                await self.close(code=4004)
                return

            is_participant = await self.check_participant()
            if not is_participant:
                logger.warning(
                    f"User {self.user.id} not participant of room {self.room_id}"
                )
                await self.close(code=4003)
                return

            await self.channel_layer.group_add(self.room_group, self.channel_name)
            await self.accept()
            await self.set_online(True)

            await self.channel_layer.group_send(
                self.room_group,
                {
                    "type": "user_status",
                    "user_id": str(self.user.id),
                    "username": self.user.username,
                    "is_online": True,
                }
            )

            logger.info(f"WebSocket connected | User={self.user.id} Room={self.room_id}")

        except Exception as e:
            logger.exception(f"Connect error: {e}")
            await self.close(code=4500)

    # =========================================================
    # TOKEN
    # =========================================================

    def get_token_from_query(self):
        try:
            query_string = self.scope.get("query_string", b"").decode()
            params = parse_qs(query_string)
            token = params.get("token")
            return token[0] if token else None
        except Exception as e:
            logger.error(f"Token parse error: {e}")
            return None

    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from rest_framework_simplejwt.exceptions import TokenError
            from django.contrib.auth import get_user_model

            User = get_user_model()
            validated_token = AccessToken(token)
            user_id = validated_token["user_id"]
            user = User.objects.filter(id=user_id).first()
            if not user:
                logger.warning(f"User not found for token user_id={user_id}")
                return None
            return user
        except Exception as e:
            logger.exception(f"JWT auth failed: {e}")
            return None

    # =========================================================
    # DISCONNECT
    # =========================================================

    async def disconnect(self, close_code):
        try:
            if hasattr(self, "room_group"):
                await self.channel_layer.group_discard(self.room_group, self.channel_name)

            if self.user and self.user.is_authenticated:
                await self.set_online(False)
                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "user_status",
                        "user_id": str(self.user.id),
                        "username": self.user.username,
                        "is_online": False,
                    }
                )
            logger.info(f"Disconnected | User={getattr(self.user, 'id', None)}")
        except Exception as e:
            logger.exception(f"Disconnect error: {e}")

    # =========================================================
    # RECEIVE
    # =========================================================

    async def receive(self, text_data):
        try:
            if not self.user or not self.user.is_authenticated:
                return

            data = json.loads(text_data)
            msg_type = data.get("type")

            # ----------------------------------
            # CHAT MESSAGE (text OR file URL)
            # ----------------------------------

            if msg_type == "chat_message":
                content = data.get("content", "").strip()

                # ── File fields — R2 se direct upload ke baad Flutter yeh bhejta hai
                file_url   = data.get("file_url", "").strip()
                file_name  = data.get("file_name", "").strip()
                file_size  = data.get("file_size")          # int bytes, can be None
                message_type = data.get("message_type", "text")

                # Validate: ya toh content hona chahiye, ya file_url
                if not content and not file_url:
                    return

                # Content length limit (text only)
                if content and len(content) > 5000:
                    return

                # message_type whitelist — arbitrary types nahi aane chahiye
                ALLOWED_TYPES = {"text", "image", "pdf", "doc", "voice", "file", "video"}
                if message_type not in ALLOWED_TYPES:
                    message_type = "text"

                message = await self.save_message(
                    content=content,
                    reply_to_id=data.get("reply_to"),
                    file_url=file_url,
                    file_name=file_name,
                    file_size=file_size,
                    message_type=message_type,
                )

                # Build WS response — Flutter MessageModel.fromWsEvent expects these fields
                msg_payload = {
                    "id": str(message.id),
                    "sender_id": str(self.user.id),
                    "sender_name": self.user.full_name,
                    "username": self.user.username,
                    "content": message.content,
                    "message_type": message.message_type,
                    "file_url": message.file_url or "",
                    "file_name": message.file_name or "",
                    "file_size": message.file_size,
                    "reply_to": str(message.reply_to.id) if message.reply_to else None,
                    "created_at": message.created_at.isoformat(),
                    "is_edited": False,
                }

                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "chat_message",
                        "message": msg_payload,
                    }
                )

            # ----------------------------------
            # TYPING
            # ----------------------------------

            elif msg_type == "typing":
                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "typing_indicator",
                        "user_id": str(self.user.id),
                        "username": self.user.username,
                        "is_typing": data.get("is_typing", False),
                    }
                )

            # ----------------------------------
            # READ RECEIPT
            # ----------------------------------

            elif msg_type in ("message_read", "messages_read"):
                await self.mark_messages_read()
                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "messages_read",
                        "user_id": str(self.user.id),
                        "room_id": str(self.room_id),
                    }
                )

            # ----------------------------------
            # PING
            # ----------------------------------

            elif msg_type == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))

        except json.JSONDecodeError:
            logger.warning("Invalid JSON received")
        except Exception as e:
            logger.exception(f"Receive error: {e}")

    # =========================================================
    # EVENTS
    # =========================================================

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def typing_indicator(self, event):
        if str(self.user.id) == event["user_id"]:
            return
        await self.send(text_data=json.dumps({
            "type": "typing",
            "user_id": event["user_id"],
            "username": event["username"],
            "is_typing": event["is_typing"],
        }))

    async def user_status(self, event):
        await self.send(text_data=json.dumps(event))

    async def messages_read(self, event):
        await self.send(text_data=json.dumps(event))

    # =========================================================
    # DATABASE
    # =========================================================

    @database_sync_to_async
    def room_exists(self):
        from .models import ChatRoom
        return ChatRoom.objects.filter(id=self.room_id).exists()

    @database_sync_to_async
    def check_participant(self):
        from .models import ChatRoom
        return ChatRoom.objects.filter(
            id=self.room_id,
            room_participants__user=self.user
        ).exists()

    @database_sync_to_async
    def save_message(
        self,
        content,
        reply_to_id=None,
        file_url="",
        file_name="",
        file_size=None,
        message_type="text",
    ):
        """
        Message save karo.
        file_url — Flutter R2 se seedha upload karta hai, sirf URL aata hai yahan.
        Backend pe koi file nahi aati — zero file-handling load.
        """
        from .models import Message, ChatRoom

        room = ChatRoom.objects.get(id=self.room_id)

        reply_to = None
        if reply_to_id:
            reply_to = Message.objects.filter(id=reply_to_id).first()

        message = Message.objects.create(
            room=room,
            sender=self.user,
            content=content,
            message_type=message_type,
            reply_to=reply_to,
            # R2 URL fields — stored as plain URL, no file upload to Django
            file_url=file_url or "",
            file_name=file_name or "",
            file_size=file_size,
        )

        room.updated_at = timezone.now()
        room.save(update_fields=["updated_at"])

        return message

    @database_sync_to_async
    def mark_messages_read(self):
        from .models import (
            ChatRoom, Message, MessageReadReceipt, ChatParticipant,
        )

        room = ChatRoom.objects.get(id=self.room_id)
        unread = Message.objects.filter(
            room=room, is_deleted=False
        ).exclude(sender=self.user)

        receipts = [
            MessageReadReceipt(message=msg, user=self.user)
            for msg in unread
        ]
        MessageReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)

        ChatParticipant.objects.filter(
            room=room, user=self.user
        ).update(last_read_at=timezone.now())

    @database_sync_to_async
    def set_online(self, status):
        if not self.user:
            return
        from django.contrib.auth import get_user_model
        User = get_user_model()
        User.objects.filter(id=self.user.id).update(
            is_online=status,
            last_seen=None if status else timezone.now()
        )


# =============================================================
# NOTIFICATIONS
# =============================================================

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.group_name = f"notifications_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def send_notification(self, event):
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": event["notification"],
        }))