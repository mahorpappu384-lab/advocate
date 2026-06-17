import asyncio
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

        logger.info(f"[CONNECT:1] room={self.room_id} | channel={self.channel_name}")

        try:
            # ── Step 1: Auth ──────────────────────────────────────────────
            # Token validation + room/participant check — PARALLEL jahan possible ho
            scope_user = self.scope.get("user")

            if scope_user and scope_user.is_authenticated:
                self.user = scope_user
                logger.info(f"[CONNECT:2a] Auth via scope_user | user_id={self.user.id}")
            else:
                token = self.get_token_from_query()
                if not token:
                    logger.warning("[CONNECT:FAIL] No token — closing 4001")
                    await self.close(code=4001)
                    return
                self.user = await self.get_user_from_token(token)

            if not self.user or not self.user.is_authenticated:
                logger.warning(f"[CONNECT:FAIL] Auth failed — closing 4001")
                await self.close(code=4001)
                return

            logger.info(f"[CONNECT:3] Auth OK | user_id={self.user.id} | username={self.user.username}")

            # ── Step 2: DB checks — PARALLEL (room_exists + check_participant ek saath) ──
            # Pehle sequential tha: ~1.5s + ~2s = ~3.5s
            # Ab parallel: max(1.5s, 2s) = ~2s  →  ~1.5s bachat
            try:
                room_exists, is_participant = await asyncio.gather(
                    self.room_exists(),
                    self.check_participant(),
                )
                logger.info(f"[CONNECT:4] room_exists={room_exists} | is_participant={is_participant}")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] DB checks crashed | {e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            if not room_exists:
                logger.warning(f"[CONNECT:FAIL] Room not found — closing 4004")
                await self.close(code=4004)
                return

            if not is_participant:
                logger.warning(f"[CONNECT:FAIL] Not a participant — closing 4003")
                await self.close(code=4003)
                return

            # ── Step 3: group_add ─────────────────────────────────────────
            try:
                await self.channel_layer.group_add(self.room_group, self.channel_name)
                logger.info(f"[CONNECT:5] group_add OK | group={self.room_group}")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] group_add crashed — Redis? | {e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            # ── Step 4: accept() — JALD SE JALD ──────────────────────────
            # set_online + broadcast accept ke BAAD background mein karo
            # Isse client ka handshake complete hota hai aur 1006 nahi aata
            await self.accept()
            logger.info(f"[CONNECT:DONE] ✅ WS accepted | user={self.user.id} | room={self.room_id}")

            # ── Step 5: Post-connect background tasks (non-blocking) ──────
            asyncio.ensure_future(self._post_connect())

        except Exception as e:
            logger.error(f"[CONNECT:FAIL] Unhandled | {e}\n{traceback.format_exc()}")
            try:
                await self.close(code=4500)
            except Exception:
                pass

    async def _post_connect(self):
        """
        accept() ke baad background mein chalta hai.
        set_online + user_status broadcast — ye accept() block nahi karta.
        Agar crash ho toh connection pe koi asar nahi padta.
        """
        try:
            await asyncio.gather(
                self.set_online(True),
                self.channel_layer.group_send(
                    self.room_group,
                    {
                        "type": "user_status",
                        "user_id": str(self.user.id),
                        "username": self.user.username,
                        "is_online": True,
                    }
                ),
            )
            logger.info(f"[POST_CONNECT] set_online + broadcast OK | user={self.user.id}")
        except Exception as e:
            logger.error(f"[POST_CONNECT] failed (non-fatal) | {e}\n{traceback.format_exc()}")

    # =========================================================
    # TOKEN
    # =========================================================

    def get_token_from_query(self):
        try:
            query_string = self.scope.get("query_string", b"").decode()
            params = parse_qs(query_string)
            token = params.get("token")
            result = token[0] if token else None
            logger.info(f"[TOKEN] found={bool(result)}")
            return result
        except Exception as e:
            logger.error(f"[TOKEN:FAIL] {e}")
            return None

    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from rest_framework_simplejwt.exceptions import TokenError
            from django.contrib.auth import get_user_model

            User = get_user_model()

            try:
                validated_token = AccessToken(token)
            except TokenError as te:
                logger.error(f"[JWT:FAIL] Token invalid/expired | {te}")
                return None

            user_id = validated_token["user_id"]
            logger.info(f"[JWT] token valid | user_id={user_id}")

            user = User.objects.filter(id=user_id, is_active=True).first()
            if not user:
                logger.warning(f"[JWT:FAIL] No active user for user_id={user_id}")
                return None

            logger.info(f"[JWT] user found | username={user.username}")
            return user

        except Exception as e:
            logger.error(f"[JWT:FAIL] Unhandled | {e}\n{traceback.format_exc()}")
            return None

    # =========================================================
    # DISCONNECT
    # =========================================================

    async def disconnect(self, close_code):
        logger.info(f"[DISCONNECT] code={close_code} | user={getattr(self.user, 'id', None)} | room={self.room_id}")
        try:
            if hasattr(self, "room_group"):
                await self.channel_layer.group_discard(self.room_group, self.channel_name)

            if self.user and self.user.is_authenticated:
                # set_online + offline broadcast — parallel
                try:
                    await asyncio.gather(
                        self.set_online(False),
                        self.channel_layer.group_send(
                            self.room_group,
                            {
                                "type": "user_status",
                                "user_id": str(self.user.id),
                                "username": self.user.username,
                                "is_online": False,
                            }
                        ),
                    )
                except Exception as e:
                    logger.error(f"[DISCONNECT:WARN] post-disconnect tasks failed (non-fatal) | {e}")

            logger.info(f"[DISCONNECT:DONE] user={getattr(self.user, 'id', None)}")

        except Exception as e:
            logger.error(f"[DISCONNECT:FAIL] {e}\n{traceback.format_exc()}")

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
            # CHAT MESSAGE
            # ----------------------------------
            if msg_type == "chat_message":
                content = data.get("content", "").strip()
                file_url = data.get("file_url", "").strip()
                file_name = data.get("file_name", "").strip()
                file_size = data.get("file_size")
                message_type = data.get("message_type", "text")

                if not content and not file_url:
                    logger.warning("[RECEIVE:FAIL] Empty message")
                    return

                if content and len(content) > 5000:
                    logger.warning(f"[RECEIVE:FAIL] Content too long | len={len(content)}")
                    return

                ALLOWED_TYPES = {"text", "image", "pdf", "doc", "voice", "file", "video"}
                if message_type not in ALLOWED_TYPES:
                    message_type = "text"

                try:
                    message = await self.save_message(
                        content=content,
                        reply_to_id=data.get("reply_to"),
                        file_url=file_url,
                        file_name=file_name,
                        file_size=file_size,
                        message_type=message_type,
                    )
                    logger.info(f"[RECEIVE] message saved | id={message.id}")
                except Exception as e:
                    logger.error(f"[RECEIVE:FAIL] save_message crashed | {e}\n{traceback.format_exc()}")
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

                await self.channel_layer.group_send(
                    self.room_group,
                    {"type": "chat_message", "message": msg_payload}
                )
                logger.info(f"[RECEIVE] broadcast OK | msg_id={message.id}")

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
                try:
                    await self.mark_messages_read()
                except Exception as e:
                    logger.error(f"[RECEIVE:FAIL] mark_messages_read crashed | {e}\n{traceback.format_exc()}")
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
                await self.send(text_data=json.dumps({"type": "pong"}))

            else:
                logger.warning(f"[RECEIVE:WARN] Unknown type={msg_type}")

        except json.JSONDecodeError as e:
            logger.warning(f"[RECEIVE:FAIL] Invalid JSON | {e}")
        except Exception as e:
            logger.error(f"[RECEIVE:FAIL] Unhandled | {e}\n{traceback.format_exc()}")

    # =========================================================
    # EVENTS
    # =========================================================

    async def chat_message(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:chat_message] {e}")

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
            logger.error(f"[EVENT:typing_indicator] {e}")

    async def user_status(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:user_status] {e}")

    async def messages_read(self, event):
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"[EVENT:messages_read] {e}")

    # =========================================================
    # DATABASE
    # =========================================================

    @database_sync_to_async
    def room_exists(self):
        from .models import ChatRoom
        result = ChatRoom.objects.filter(id=self.room_id).exists()
        logger.info(f"[DB:room_exists] result={result}")
        return result

    @database_sync_to_async
    def check_participant(self):
        from .models import ChatRoom
        # room_exists aur check_participant dono parallel chalte hain
        # isliye user_id yahan safe hai — auth step pehle complete ho chuka hai
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
            file_url=file_url or "",
            file_name=file_name or "",
            file_size=file_size,
        )
        # room.updated_at ek hi query mein update karo
        room.updated_at = timezone.now()
        room.save(update_fields=["updated_at"])
        logger.info(f"[DB:save_message] saved | id={message.id}")
        return message

    @database_sync_to_async
    def mark_messages_read(self):
        from .models import ChatRoom, Message, MessageReadReceipt, ChatParticipant

        room = ChatRoom.objects.get(id=self.room_id)
        unread = Message.objects.filter(
            room=room, is_deleted=False
        ).exclude(sender=self.user)

        receipts = [MessageReadReceipt(message=msg, user=self.user) for msg in unread]
        MessageReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)
        ChatParticipant.objects.filter(room=room, user=self.user).update(
            last_read_at=timezone.now()
        )
        logger.info(f"[DB:mark_read] done | room={self.room_id}")

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
        logger.info(f"[DB:set_online] user={self.user.id} | online={status}")


# =============================================================
# NOTIFICATIONS
# =============================================================

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            logger.warning("[NOTIF:CONNECT:FAIL] Unauthenticated — closing 4001")
            await self.close(code=4001)
            return

        self.group_name = f"notifications_{self.user.id}"
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            logger.info(f"[NOTIF:CONNECT:DONE] user_id={self.user.id}")
        except Exception as e:
            logger.error(f"[NOTIF:CONNECT:FAIL] {e}\n{traceback.format_exc()}")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception as e:
                logger.error(f"[NOTIF:DISCONNECT:FAIL] {e}")

    async def receive(self, text_data):
        pass

    async def send_notification(self, event):
        try:
            await self.send(text_data=json.dumps({
                "type": "notification",
                "notification": event["notification"],
            }))
        except Exception as e:
            logger.error(f"[NOTIF:send_notification] {e}\n{traceback.format_exc()}")