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
        self._accepted = False

        logger.info(f"[CONNECT:1] room={self.room_id} | channel={self.channel_name}")

        # ── ✅ FIX: accept() SABSE PEHLE — koi DB/auth check se pehle ─────
        # Pehle yahan auth + 2 DB queries (room_exists, check_participant) ke
        # baad accept() hota tha — ye sab milke kabhi kabhi 2-4s+ le lete the.
        # Render starter plan (1 worker, slow/cold Postgres) pe proxy ka
        # WS-upgrade timeout isse pehle hi cross ho jaata tha, aur browser ko
        # "Unexpected response code: 500" milta tha — fir Flutter turant
        # disconnect karke retry karta, jabki server abhi DB query mein hi
        # busy hota tha. Isi wajah se kabhi consumer ka koi log bhi nahi dikhta.
        #
        # Ab handshake ko jitna jaldi ho sake complete karo (accept()), aur
        # auth/room/participant validation baad mein karo. Agar validation
        # fail ho, tab bhi close() kar dete hain — bas connection establish
        # hone ke baad, proxy timeout window se bahar.
        try:
            await self.accept()
            self._accepted = True
            logger.info(f"[CONNECT:2] ✅ WS accepted (pre-auth) | room={self.room_id}")
        except Exception as e:
            logger.error(f"[CONNECT:FAIL] accept() crashed | {e}\n{traceback.format_exc()}")
            return

        try:
            # ── Step 1: Auth ──────────────────────────────────────────────
            scope_user = self.scope.get("user")

            if scope_user and getattr(scope_user, "is_authenticated", False):
                self.user = scope_user
                logger.info(f"[CONNECT:3a] Auth via scope_user | user_id={self.user.id}")
            else:
                token = self.get_token_from_query()
                if not token:
                    logger.warning("[CONNECT:FAIL] No token — closing 4001")
                    await self.close(code=4001)
                    return
                self.user = await self.get_user_from_token(token)

            if not self.user or not self.user.is_authenticated:
                logger.warning("[CONNECT:FAIL] Auth failed — closing 4001")
                await self.close(code=4001)
                return

            logger.info(f"[CONNECT:4] Auth OK | user_id={self.user.id} | username={self.user.username}")

            # ── Step 2: room_exists + is_participant — EK QUERY mein combine ──
            # Pehle 2 alag DB calls parallel chalti thi. Ab ek hi query se
            # dono confirm ho jaate hain — round trips kam.
            try:
                is_participant = await self.check_participant()
                logger.info(f"[CONNECT:5] is_participant={is_participant}")
            except Exception as e:
                logger.error(f"[CONNECT:FAIL] DB check crashed | {e}\n{traceback.format_exc()}")
                await self.close(code=4500)
                return

            if not is_participant:
                # Room missing ya user participant nahi — dono cases yahan aate hain.
                # (room_exists() ko separately call karke 4004 vs 4003 differentiate
                # kar sakte ho agar frontend ko alag handling chahiye.)
                logger.warning("[CONNECT:FAIL] Room missing or not a participant — closing 4003")
                await self.close(code=4003)
                return

            # ── Step 3: group_add — retry with backoff ────────────────────
            # ✅ FIX: Render pe Redis ka idle TCP connection silently drop ho
            # jaata hai (network timeout ~30-60s). Pehli baar group_add pe
            # "Connection lost" aata tha — ye stale pooled connection ki
            # wajah se tha, actual Redis service down nahi tha.
            # settings.py mein health_check_interval=15 se ye problem mostly
            # solve ho gayi hai, lekin ek retry yahan double safety net hai —
            # pehli baar "Connection lost" aaye toh redis pool nayi connection
            # banata hai, doosri baar pe kaam ho jaata hai.
            group_add_ok = False
            for attempt in range(1, 3):  # max 2 tries
                try:
                    await self.channel_layer.group_add(self.room_group, self.channel_name)
                    logger.info(f"[CONNECT:6] group_add OK (attempt {attempt}) | group={self.room_group}")
                    group_add_ok = True
                    break
                except Exception as e:
                    err_str = str(e)
                    logger.warning(
                        f"[CONNECT:group_add] attempt {attempt} failed | {err_str}"
                    )
                    if attempt < 2:
                        # 500ms ruko — pool nayi connection banaye
                        await asyncio.sleep(0.5)
                    else:
                        logger.error(
                            f"[CONNECT:FAIL] group_add failed after 2 attempts — Redis down?\n{traceback.format_exc()}"
                        )

            if not group_add_ok:
                await self.close(code=4500)
                return

            logger.info(f"[CONNECT:DONE] ✅ Fully validated | user={self.user.id} | room={self.room_id}")

            # ── Step 4: Post-connect background tasks (non-blocking) ──────
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
                    # ✅ FIX: Client ko error bata do taaki wo retry kar sake
                    # Pehle silently return hota tha — sender ko lagta tha message gaya
                    # jabki DB mein save hi nahi hua tha
                    try:
                        await self.send(text_data=json.dumps({
                            "type": "error",
                            "code": "save_failed",
                            "message": "Message could not be saved. Please retry.",
                        }))
                    except Exception:
                        pass
                    return

                msg_payload = {
                    "id": str(message.id),
                    # ✅ FIX: room_id bhi bhejo — Flutter side pe wrong-room guard ke liye
                    "room_id": str(self.room_id),
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

                # ✅ SPEED FIX: Sender ko TURANT ACK bhejo + group broadcast parallel mein
                # Pehle: group_send → Redis → apna channel → send() — ye 3 hops tha
                # Ab: sender ko seedha send() + baaki ko group_send() — parallel
                # Result: sender ki screen pe message ~100-200ms mein, receiver pe ~200-400ms
                await asyncio.gather(
                    self.send(text_data=json.dumps({"type": "chat_message", "message": msg_payload})),
                    self.channel_layer.group_send(
                        self.room_group,
                        {"type": "chat_message", "message": msg_payload}
                    ),
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
            # ✅ SPEED FIX: Sender ko group_send se duplicate mat bhejo.
            # receive() mein sender ko seedha send() ho chuka hai (direct ACK).
            # group_send wala event apne hi channel pe bhi aata hai — isse
            # sender ko double message milta tha (temp replace hone ke baad
            # fir se same msg_id aata tha — Flutter side duplicate check tha
            # isliye UI mein nahi dikhta tha, lekin unnecessary processing hoti).
            # Ab sender_id check karo — apna event skip karo.
            msg = event.get("message", {})
            if msg.get("sender_id") == str(getattr(self.user, 'id', None)):
                return  # Already got direct ACK in receive()
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

        # ✅ SPEED FIX: Room object fetch karne ki zaroorat NAHI hai.
        # connect() mein check_participant() se room already validated ho chuka
        # hai. Message.objects.create() mein room_id (FK) seedha pass karo —
        # Django ek extra SELECT round-trip bachata hai.
        # Pehle: filter().first() → SELECT * FROM chatroom — extra DB call
        # Ab: room_id=self.room_id → sirf INSERT, koi SELECT nahi
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.filter(
                    id=reply_to_id, room_id=self.room_id
                ).only('id').first()
            except Exception:
                reply_to = None  # invalid reply_to — silently ignore

        now = timezone.now()
        message = Message.objects.create(
            room_id=self.room_id,      # ← FK direct pass — no SELECT needed
            sender=self.user,
            content=content,
            message_type=message_type,
            reply_to=reply_to,
            file_url=file_url or "",
            file_name=file_name or "",
            file_size=file_size,
        )
        # Single UPDATE — same as before, already optimal
        ChatRoom.objects.filter(id=self.room_id).update(updated_at=now)
        logger.info(f"[DB:save_message] saved | id={message.id}")
        return message

    @database_sync_to_async
    def mark_messages_read(self):
        from .models import Message, MessageReadReceipt, ChatParticipant

        # ✅ SPEED FIX: ChatRoom.objects.get() hata diya — ye extra SELECT tha.
        # room_id seedha FK filter mein use karo — Django ORM join karega.
        # Pehle: get(room) → filter(room=room) = 2 queries
        # Ab: filter(room_id=self.room_id) = 1 query
        now = timezone.now()
        unread = Message.objects.filter(
            room_id=self.room_id, is_deleted=False
        ).exclude(sender=self.user).only('id')  # sirf id chahiye — SELECT * nahi

        receipts = [MessageReadReceipt(message=msg, user=self.user) for msg in unread]
        MessageReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)
        ChatParticipant.objects.filter(
            room_id=self.room_id, user=self.user
        ).update(last_read_at=now)
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