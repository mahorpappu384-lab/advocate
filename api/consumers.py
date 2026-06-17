import json
import logging
import traceback
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

        logger.info(f"[CONNECT:1] Incoming WS | room={self.room_id} | scope_type={self.scope.get('type')} | headers={dict(self.scope.get('headers', []))}")

        try:
            # ── Step 1: Auth ──────────────────────────────────────────────
            scope_user = self.scope.get("user")
            logger.info(f"[CONNECT:2] scope_user={scope_user} | is_authenticated={getattr(scope_user, 'is_authenticated', False)}")

            if scope_user and scope_user.is_authenticated:
                self.user = scope_user
                logger.info(f"[CONNECT:3a] Auth via scope_user | user_id={self.user.id}")
            else:
                token = self.get_token_from_query()
                logger.info(f"[CONNECT:3b] No scope_user — trying query token | token_present={bool(token)} | token_preview={token[:20] + '...' if token else None}")
                if token:
                    self.user = await self.get_user_from_token(token)
                    logger.info(f"[CONNECT:3c] Token auth result | user={self.user} | user_id={getattr(self.user, 'id', None)}")

            if not self.user or not self.user.is_authenticated:
                logger.warning(f"[CONNECT:FAIL] Authentication failed | user={self.user} | closing with 4001")
                await self.close(code=4001)
                return

            logger.info(f"[CONNECT:4] Auth OK | user_id={self.user.id} | username={self.user.username}")

            # ── Step 2: Room exists? ──────────────────────────────────────
            logger.info(f"[CONNECT:5] Checking room_exists | room_id={self.room_id}")
            try:
                room_exists = await self.room_exists()
                logger.info(f"[CONNECT:6] room_exists={room_exists}")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] room_exists() crashed | error={e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            if not room_exists:
                logger.warning(f"[CONNECT:FAIL] Room not found | room_id={self.room_id} | closing with 4004")
                await self.close(code=4004)
                return

            # ── Step 3: Is participant? ───────────────────────────────────
            logger.info(f"[CONNECT:7] Checking check_participant | user_id={self.user.id} | room_id={self.room_id}")
            try:
                is_participant = await self.check_participant()
                logger.info(f"[CONNECT:8] is_participant={is_participant}")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] check_participant() crashed | error={e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            if not is_participant:
                logger.warning(f"[CONNECT:FAIL] Not a participant | user_id={self.user.id} | room_id={self.room_id} | closing with 4003")
                await self.close(code=4003)
                return

            # ── Step 4: group_add ─────────────────────────────────────────
            logger.info(f"[CONNECT:9] group_add | group={self.room_group} | channel={self.channel_name}")
            try:
                await self.channel_layer.group_add(self.room_group, self.channel_name)
                logger.info(f"[CONNECT:10] group_add OK")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] group_add() crashed — Redis problem? | error={e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            # ── Step 5: accept ────────────────────────────────────────────
            logger.info(f"[CONNECT:11] Calling accept()")
            try:
                await self.accept()
                logger.info(f"[CONNECT:12] accept() OK — WS handshake complete")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] accept() crashed | error={e}\n{traceback.format_exc()}")
                return

            # ── Step 6: set_online ────────────────────────────────────────
            logger.info(f"[CONNECT:13] set_online(True)")
            try:
                await self.set_online(True)
                logger.info(f"[CONNECT:14] set_online OK")
            except Exception as e:
                logger.error(f"[CONNECT:WARN] set_online() crashed (non-fatal) | error={e}\n{traceback.format_exc()}")
                # Non-fatal — continue

            # ── Step 7: broadcast user_status ────────────────────────────
            logger.info(f"[CONNECT:15] Broadcasting user_status to group={self.room_group}")
            try:
                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "user_status",
                        "user_id": str(self.user.id),
                        "username": self.user.username,
                        "is_online": True,
                    }
                )
                logger.info(f"[CONNECT:16] group_send user_status OK")
            except Exception as e:
                logger.error(f"[CONNECT:WARN] group_send user_status crashed (non-fatal) | error={e}\n{traceback.format_exc()}")
                # Non-fatal — user is connected, just status broadcast failed

            logger.info(f"[CONNECT:DONE] ✅ WebSocket fully connected | user_id={self.user.id} | room={self.room_id}")

        except Exception as e:
            logger.error(f"[CONNECT:FAIL] Unhandled exception in connect() | error={e}\n{traceback.format_exc()}")
            try:
                await self.close(code=4500)
            except Exception as close_err:
                logger.error(f"[CONNECT:FAIL] close() also failed | error={close_err}")

    # =========================================================
    # TOKEN
    # =========================================================

    def get_token_from_query(self):
        try:
            query_string = self.scope.get("query_string", b"").decode()
            logger.info(f"[TOKEN:1] raw query_string={query_string[:100]}")
            params = parse_qs(query_string)
            logger.info(f"[TOKEN:2] parsed params keys={list(params.keys())}")
            token = params.get("token")
            result = token[0] if token else None
            logger.info(f"[TOKEN:3] token found={bool(result)}")
            return result
        except Exception as e:
            logger.error(f"[TOKEN:FAIL] Token parse error | error={e}\n{traceback.format_exc()}")
            return None

    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            logger.info(f"[JWT:1] Validating token | preview={token[:20]}...")
            from rest_framework_simplejwt.tokens import AccessToken
            from rest_framework_simplejwt.exceptions import TokenError
            from django.contrib.auth import get_user_model

            User = get_user_model()
            logger.info(f"[JWT:2] User model={User} | db_table={User._meta.db_table}")

            try:
                validated_token = AccessToken(token)
            except TokenError as te:
                logger.error(f"[JWT:FAIL] Token invalid/expired | error={te}")
                return None

            user_id = validated_token["user_id"]
            logger.info(f"[JWT:3] Token valid | user_id={user_id}")

            try:
                user = User.objects.filter(id=user_id).first()
            except Exception as db_err:
                logger.error(f"[JWT:FAIL] DB query failed | table={User._meta.db_table} | error={db_err}\n{traceback.format_exc()}")
                return None

            if not user:
                logger.warning(f"[JWT:FAIL] No user found for user_id={user_id}")
                return None

            logger.info(f"[JWT:4] User found | user_id={user.id} | username={user.username} | is_active={user.is_active}")
            return user

        except Exception as e:
            logger.error(f"[JWT:FAIL] Unhandled exception | error={e}\n{traceback.format_exc()}")
            return None

    # =========================================================
    # DISCONNECT
    # =========================================================

    async def disconnect(self, close_code):
        logger.info(f"[DISCONNECT:1] close_code={close_code} | user_id={getattr(self.user, 'id', None)} | room={self.room_id}")
        try:
            if hasattr(self, "room_group"):
                logger.info(f"[DISCONNECT:2] group_discard | group={self.room_group}")
                await self.channel_layer.group_discard(self.room_group, self.channel_name)
                logger.info(f"[DISCONNECT:3] group_discard OK")

            if self.user and self.user.is_authenticated:
                logger.info(f"[DISCONNECT:4] set_online(False)")
                try:
                    await self.set_online(False)
                    logger.info(f"[DISCONNECT:5] set_online OK")
                except Exception as e:
                    logger.error(f"[DISCONNECT:WARN] set_online(False) failed (non-fatal) | error={e}\n{traceback.format_exc()}")

                # NOTE: group_send AFTER group_discard — this user won't receive it
                # but other participants will
                logger.info(f"[DISCONNECT:6] Broadcasting offline status to group={self.room_group}")
                try:
                    await self.channel_layer.group_send(
                        self.room_group,
                        {
                            "type": "user_status",
                            "user_id": str(self.user.id),
                            "username": self.user.username,
                            "is_online": False,
                        }
                    )
                    logger.info(f"[DISCONNECT:7] Offline broadcast OK")
                except Exception as e:
                    logger.error(f"[DISCONNECT:WARN] Offline broadcast failed (non-fatal) | error={e}\n{traceback.format_exc()}")

            logger.info(f"[DISCONNECT:DONE] Disconnected cleanly | user_id={getattr(self.user, 'id', None)}")

        except Exception as e:
            logger.error(f"[DISCONNECT:FAIL] Unhandled exception | error={e}\n{traceback.format_exc()}")

    # =========================================================
    # RECEIVE
    # =========================================================

    async def receive(self, text_data):
        logger.info(f"[RECEIVE:1] raw={text_data[:200]}")
        try:
            if not self.user or not self.user.is_authenticated:
                logger.warning(f"[RECEIVE:FAIL] Unauthenticated receive — ignoring")
                return

            data = json.loads(text_data)
            msg_type = data.get("type")
            logger.info(f"[RECEIVE:2] type={msg_type}")

            # ----------------------------------
            # CHAT MESSAGE
            # ----------------------------------
            if msg_type == "chat_message":
                content = data.get("content", "").strip()
                file_url = data.get("file_url", "").strip()
                file_name = data.get("file_name", "").strip()
                file_size = data.get("file_size")
                message_type = data.get("message_type", "text")

                logger.info(f"[RECEIVE:3] chat_message | content_len={len(content)} | file_url={bool(file_url)} | message_type={message_type}")

                if not content and not file_url:
                    logger.warning(f"[RECEIVE:FAIL] Empty message — no content and no file_url")
                    return

                if content and len(content) > 5000:
                    logger.warning(f"[RECEIVE:FAIL] Content too long | len={len(content)}")
                    return

                ALLOWED_TYPES = {"text", "image", "pdf", "doc", "voice", "file", "video"}
                if message_type not in ALLOWED_TYPES:
                    logger.warning(f"[RECEIVE:WARN] Unknown message_type={message_type} — defaulting to text")
                    message_type = "text"

                logger.info(f"[RECEIVE:4] Saving message to DB")
                try:
                    message = await self.save_message(
                        content=content,
                        reply_to_id=data.get("reply_to"),
                        file_url=file_url,
                        file_name=file_name,
                        file_size=file_size,
                        message_type=message_type,
                    )
                    logger.info(f"[RECEIVE:5] Message saved | id={message.id}")
                except Exception as e:
                    logger.error(f"[RECEIVE:FAIL] save_message() crashed | error={e}\n{traceback.format_exc()}")
                    return

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

                logger.info(f"[RECEIVE:6] Broadcasting to group={self.room_group}")
                await self.channel_layer.group_send(
                    self.room_group,
                    {"type": "chat_message", "message": msg_payload}
                )
                logger.info(f"[RECEIVE:7] Broadcast OK | msg_id={message.id}")

            # ----------------------------------
            # TYPING
            # ----------------------------------
            elif msg_type == "typing":
                is_typing = data.get("is_typing", False)
                logger.info(f"[RECEIVE:typing] user={self.user.username} | is_typing={is_typing}")
                await self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "typing_indicator",
                        "user_id": str(self.user.id),
                        "username": self.user.username,
                        "is_typing": is_typing,
                    }
                )

            # ----------------------------------
            # READ RECEIPT
            # ----------------------------------
            elif msg_type in ("message_read", "messages_read"):
                logger.info(f"[RECEIVE:read] Marking messages read | user={self.user.id} | room={self.room_id}")
                try:
                    await self.mark_messages_read()
                    logger.info(f"[RECEIVE:read] mark_messages_read OK")
                except Exception as e:
                    logger.error(f"[RECEIVE:FAIL] mark_messages_read crashed | error={e}\n{traceback.format_exc()}")
                    return
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
                logger.info(f"[RECEIVE:ping] pong → {self.user.username}")
                await self.send(text_data=json.dumps({"type": "pong"}))

            else:
                logger.warning(f"[RECEIVE:WARN] Unknown msg_type={msg_type}")

        except json.JSONDecodeError as e:
            logger.warning(f"[RECEIVE:FAIL] Invalid JSON | error={e} | raw={text_data[:200]}")
        except Exception as e:
            logger.error(f"[RECEIVE:FAIL] Unhandled exception | error={e}\n{traceback.format_exc()}")

    # =========================================================
    # EVENTS
    # =========================================================

    async def chat_message(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:chat_message] send failed | error={e}\n{traceback.format_exc()}")

    async def typing_indicator(self, event):
        try:
            if str(self.user.id) == event["user_id"]:
                return
            await self.send(text_data=json.dumps({
                "type": "typing",
                "user_id": event["user_id"],
                "username": event["username"],
                "is_typing": event["is_typing"],
            }))
        except Exception as e:
            logger.error(f"[EVENT:typing_indicator] send failed | error={e}\n{traceback.format_exc()}")

    async def user_status(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:user_status] send failed | error={e}\n{traceback.format_exc()}")

    async def messages_read(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:messages_read] send failed | error={e}\n{traceback.format_exc()}")

    # =========================================================
    # DATABASE
    # =========================================================

    @database_sync_to_async
    def room_exists(self):
        from .models import ChatRoom
        logger.info(f"[DB:room_exists] querying | room_id={self.room_id}")
        result = ChatRoom.objects.filter(id=self.room_id).exists()
        logger.info(f"[DB:room_exists] result={result}")
        return result

    @database_sync_to_async
    def check_participant(self):
        from .models import ChatRoom
        logger.info(f"[DB:check_participant] querying | room_id={self.room_id} | user_id={self.user.id}")
        result = ChatRoom.objects.filter(
            id=self.room_id,
            room_participants__user=self.user
        ).exists()
        logger.info(f"[DB:check_participant] result={result}")
        return result

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
        from .models import Message, ChatRoom
        logger.info(f"[DB:save_message] room={self.room_id} | type={message_type} | content_len={len(content)} | file={bool(file_url)}")

        room = ChatRoom.objects.get(id=self.room_id)
        reply_to = None
        if reply_to_id:
            reply_to = Message.objects.filter(id=reply_to_id).first()
            logger.info(f"[DB:save_message] reply_to found={reply_to is not None}")

        message = Message.objects.create(
            room=room,
            sender=self.user,
            content=content,
            message_type=message_type,
            reply_to=reply_to,
            file_url=file_url or "",
            file_name=file_name or "",
            file_size=file_size,
        )
        room.updated_at = timezone.now()
        room.save(update_fields=["updated_at"])
        logger.info(f"[DB:save_message] saved | id={message.id}")
        return message

    @database_sync_to_async
    def mark_messages_read(self):
        from .models import ChatRoom, Message, MessageReadReceipt, ChatParticipant
        logger.info(f"[DB:mark_read] room={self.room_id} | user={self.user.id}")

        room = ChatRoom.objects.get(id=self.room_id)
        unread = Message.objects.filter(
            room=room, is_deleted=False
        ).exclude(sender=self.user)
        count = unread.count()
        logger.info(f"[DB:mark_read] unread_count={count}")

        receipts = [MessageReadReceipt(message=msg, user=self.user) for msg in unread]
        MessageReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)
        ChatParticipant.objects.filter(room=room, user=self.user).update(last_read_at=timezone.now())
        logger.info(f"[DB:mark_read] done | marked={count}")

    @database_sync_to_async
    def set_online(self, status):
        if not self.user:
            logger.warning(f"[DB:set_online] user is None — skipping")
            return
        from django.contrib.auth import get_user_model
        User = get_user_model()
        logger.info(f"[DB:set_online] user_id={self.user.id} | status={status}")
        updated = User.objects.filter(id=self.user.id).update(
            is_online=status,
            last_seen=None if status else timezone.now()
        )
        logger.info(f"[DB:set_online] rows_updated={updated}")


# =============================================================
# NOTIFICATIONS
# =============================================================

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope.get("user")
        logger.info(f"[NOTIF:CONNECT] user={self.user} | authenticated={getattr(self.user, 'is_authenticated', False)}")

        if not self.user or not self.user.is_authenticated:
            logger.warning(f"[NOTIF:CONNECT:FAIL] Unauthenticated — closing 4001")
            await self.close(code=4001)
            return

        self.group_name = f"notifications_{self.user.id}"
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            logger.info(f"[NOTIF:CONNECT:DONE] connected | user_id={self.user.id} | group={self.group_name}")
        except Exception as e:
            logger.error(f"[NOTIF:CONNECT:FAIL] error={e}\n{traceback.format_exc()}")

    async def disconnect(self, close_code):
        logger.info(f"[NOTIF:DISCONNECT] code={close_code} | user={getattr(self.user, 'id', None)}")
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception as e:
                logger.error(f"[NOTIF:DISCONNECT:FAIL] group_discard error={e}")

    async def receive(self, text_data):
        pass

    async def send_notification(self, event):
        try:
            await self.send(text_data=json.dumps({
                "type": "notification",
                "notification": event["notification"],
            }))
        except Exception as e:
            logger.error(f"[NOTIF:send_notification] failed | error={e}\n{traceback.format_exc()}")