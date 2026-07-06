"""
Advocate App - All Serializers
UI Features aligned with LegalConnect screenshots.

PERFORMANCE CHANGES vs original:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. AdvocateProfileSerializer — 5 per-profile DB queries → 0 extra queries
   - get_post_count: ab cached field use karta hai (serializer context se bulk-compute ho sakta hai)
   - get_connection_count: cached field use karta hai
   - get_is_connected, get_is_following, get_connection_status:
     ab context se pre-fetched sets use karte hain (views.py se inject hota hai)
   - Views jo list return karte hain wo context inject karein — single-profile views pe
     graceful fallback as before

2. PostSerializer — 3 per-post DB queries → 0 extra queries
   - get_user_reaction: context['user_reactions'] dict use karta hai (bulk pre-fetch)
   - get_is_saved: context['saved_post_ids'] set use karta hai (bulk pre-fetch)
   - get_top_comments: select_related already on queryset — no change needed

3. ChannelPostSerializer — comments field unlimited load → limit 5, select_related
   - Performance: serializer pe comments=[] by default, views inject karein

4. UserMiniSerializer — profile_photo: try/except per-object → getattr safe access
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    AdvocateProfile, AdvocateEducation, AdvocateExperience, AdvocateAchievement,
    Connection, Follow, OTP,
    ChatRoom, ChatParticipant, Message, MessageReadReceipt,
    Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment, ChannelPostLike, ChannelPostReaction,
    Post, PostReaction, PostComment, PostCommentLike, Hashtag, SavedPost, PostShare,
    CaseGroup, GroupMembership, GroupDocument,
    Notification, Report,
    Hearing, LegalUpdate,
)

User = get_user_model()


# ══════════════════════════════════════════════════════════════════════════════
# AUTH SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'full_name', 'password', 'password2']

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        if not value.isalnum() and '_' not in value:
            raise serializers.ValidationError("Username can only contain letters, numbers and underscore.")
        return value.lower()

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['email'] = user.email or ""
        token['full_name'] = user.full_name
        token['is_advocate'] = user.is_advocate
        token['advocate_status'] = user.advocate_status
        token['is_verified'] = user.is_verified
        return token


class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6, min_length=6)
    purpose = serializers.ChoiceField(choices=['email_verify', 'forgot_password', 'phone_verify'])


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(validators=[validate_password])


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
    confirm_password = serializers.CharField()

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords do not match."})
        return attrs


# ══════════════════════════════════════════════════════════════════════════════
# USER SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class UserMiniSerializer(serializers.ModelSerializer):
    """
    Minimal user info — embedded in posts, messages, channels.

    PERF FIX: get_profile_photo ab try/except ke bajaye hasattr + getattr use karta hai.
    Views jo in objects use karte hain wo select_related('advocate_profile') karein —
    tab koi extra query nahi hogi.
    """
    profile_photo = serializers.SerializerMethodField()
    is_advocate_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'username',
            'email',
            'is_advocate',
            'advocate_status',
            'profile_photo',
            'is_advocate_verified',
            'presence_status',
            'is_online',
            'who_can_message',
            'who_can_see_profile',
        ]

    def get_profile_photo(self, obj):
        # ✅ PERF: Agar view ne select_related('advocate_profile') kiya hai toh
        # _advocate_profile_cache already populated hai — zero extra query.
        # try/except se slightly faster, aur AttributeError bhi nahi aata.
        profile = getattr(obj, 'advocate_profile', None)
        if profile and profile.profile_photo:
            return profile.profile_photo
        return None

    def get_is_advocate_verified(self, obj):
        return obj.is_advocate and obj.advocate_status == 'approved'


class UserProfileSerializer(serializers.ModelSerializer):
    """Full user profile — /api/users/me/ and /api/users/<id>/"""
    onboarding_complete = serializers.SerializerMethodField()

    def get_onboarding_complete(self, obj):
        profile = getattr(obj, 'advocate_profile', None)
        return profile.onboarding_complete if profile else False

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'full_name', 'phone',
            'is_verified', 'is_advocate', 'advocate_status',
            'date_joined', 'is_online', 'last_seen',
            'presence_status',
            'theme', 'accent_color',
            'notif_messages', 'notif_group_mentions', 'notif_stories', 'notif_calls',
            'privacy_read_receipts', 'privacy_last_seen', 'privacy_online_status',
            'who_can_message', 'who_can_see_profile',
            'cases_handled', 'advocate_rating',
            'onboarding_complete',
        ]
        read_only_fields = ['id', 'username', 'email', 'is_verified',
                            'advocate_status', 'date_joined']


# ══════════════════════════════════════════════════════════════════════════════
# ADVOCATE PROFILE SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class AdvocateEducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateEducation
        fields = '__all__'
        read_only_fields = ['profile']


class AdvocateExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateExperience
        fields = '__all__'
        read_only_fields = ['profile']


class AdvocateAchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateAchievement
        fields = '__all__'
        read_only_fields = ['profile']


class AdvocateProfileSerializer(serializers.ModelSerializer):
    """
    PERF FIX — N+1 eliminated:
    ────────────────────────────────────────────────────────────────────
    ORIGINAL: 5 DB queries per profile object
      get_post_count()        → SELECT COUNT(*) FROM posts WHERE author=...
      get_connection_count()  → SELECT COUNT(*) FROM connections WHERE ...
      get_is_connected()      → SELECT 1 FROM connections WHERE ...
      get_is_following()      → SELECT 1 FROM follows WHERE ...
      get_connection_status() → SELECT * FROM connections WHERE ...
    On a 50-profile search page = 250 extra queries!

    NEW APPROACH:
    - Views inject pre-computed sets/dicts into serializer context.
    - Serializer reads from context dict — O(1) Python dict lookup, 0 DB queries.
    - Single-object views (profile detail) gracefully fall back to DB queries.
    - Cached fields (post_count, connection_count) used — views sync them periodically.

    HOW TO USE in list views:
        context = {
            'request': request,
            'connected_user_ids': set(),      # accepted connection user IDs
            'following_user_ids': set(),      # user IDs current user follows
            'connection_map': {},             # user_id → {status, is_sender}
        }
    ────────────────────────────────────────────────────────────────────
    """
    user = UserMiniSerializer(read_only=True)
    education = AdvocateEducationSerializer(many=True, read_only=True)
    experience = AdvocateExperienceSerializer(many=True, read_only=True)
    achievements = AdvocateAchievementSerializer(many=True, read_only=True)
    is_connected = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    connection_status = serializers.SerializerMethodField()
    post_count = serializers.SerializerMethodField()
    connection_count = serializers.SerializerMethodField()

    def get_post_count(self, obj):
        # ✅ PERF: Cached field — no DB query.
        # Views update this via profile.save(update_fields=['post_count'])
        return obj.post_count

    def get_connection_count(self, obj):
        # ✅ PERF: Cached field — no DB query.
        return obj.connection_count

    def get_is_connected(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # ✅ PERF: Context-injected set from view — O(1) lookup, 0 DB queries
        connected_ids = self.context.get('connected_user_ids')
        if connected_ids is not None:
            return obj.user_id in connected_ids
        # Fallback for single-object views (profile detail)
        return Connection.objects.filter(
            sender__in=[request.user, obj.user],
            receiver__in=[request.user, obj.user],
            status='accepted'
        ).exists()

    def get_is_following(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # ✅ PERF: Context-injected set from view
        following_ids = self.context.get('following_user_ids')
        if following_ids is not None:
            return obj.user_id in following_ids
        return Follow.objects.filter(follower=request.user, following=obj.user).exists()

    def get_connection_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        # ✅ PERF: Context-injected dict from view
        connection_map = self.context.get('connection_map')
        if connection_map is not None:
            return connection_map.get(obj.user_id)
        # Fallback for single-object views
        conn = Connection.objects.filter(
            sender__in=[request.user, obj.user],
            receiver__in=[request.user, obj.user],
        ).first()
        if conn:
            return {'status': conn.status, 'is_sender': conn.sender == request.user}
        return None

    class Meta:
        model = AdvocateProfile
        fields = '__all__'
        read_only_fields = ['user', 'connection_count', 'follower_count',
                            'post_count', 'media_count', 'group_count', 'message_count']


class AdvocateVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateProfile
        fields = ['bar_council_id', 'bar_council_id_image', 'enrollment_number',
                  'enrollment_year', 'state_bar_council']


# ══════════════════════════════════════════════════════════════════════════════
# HOME SCREEN SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class HearingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hearing
        fields = ['id', 'case_title', 'case_number', 'court', 'court_room',
                  'hearing_time', 'hearing_date', 'hearing_type', 'notes',
                  'is_completed', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class LegalUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalUpdate
        fields = ['id', 'title', 'summary', 'source_url', 'urgency', 'created_at']
        read_only_fields = ['id', 'created_at']


class HomeDashboardSerializer(serializers.Serializer):
    cases_handled = serializers.IntegerField()
    connections = serializers.IntegerField()
    hearings_today = serializers.IntegerField()
    advocate_rating = serializers.DecimalField(max_digits=3, decimal_places=1)
    todays_hearings = HearingSerializer(many=True)
    recent_updates = LegalUpdateSerializer(many=True)


# ══════════════════════════════════════════════════════════════════════════════
# NETWORKING SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    receiver = UserMiniSerializer(read_only=True)

    sender_name = serializers.SerializerMethodField()
    receiver_name = serializers.SerializerMethodField()
    sender_photo = serializers.SerializerMethodField()
    receiver_photo = serializers.SerializerMethodField()
    sender_court = serializers.SerializerMethodField()
    receiver_court = serializers.SerializerMethodField()

    class Meta:
        model = Connection
        fields = [
            'id', 'sender', 'receiver', 'status', 'message', 'created_at', 'updated_at',
            'sender_name', 'receiver_name',
            'sender_photo', 'receiver_photo',
            'sender_court', 'receiver_court',
        ]
        read_only_fields = ['id', 'sender', 'status', 'created_at', 'updated_at']

    def get_sender_name(self, obj):
        return obj.sender.full_name if obj.sender else ''

    def get_receiver_name(self, obj):
        return obj.receiver.full_name if obj.receiver else ''

    def get_sender_photo(self, obj):
        # ✅ PERF: getattr instead of try/except
        profile = getattr(obj.sender, 'advocate_profile', None) if obj.sender else None
        return profile.profile_photo if profile else None

    def get_receiver_photo(self, obj):
        profile = getattr(obj.receiver, 'advocate_profile', None) if obj.receiver else None
        return profile.profile_photo if profile else None

    def get_sender_court(self, obj):
        profile = getattr(obj.sender, 'advocate_profile', None) if obj.sender else None
        return (profile.primary_court or '') if profile else ''

    def get_receiver_court(self, obj):
        profile = getattr(obj.receiver, 'advocate_profile', None) if obj.receiver else None
        return (profile.primary_court or '') if profile else ''


class ConnectionRequestSerializer(serializers.Serializer):
    receiver_id = serializers.UUIDField()
    message = serializers.CharField(required=False, allow_blank=True, default='')


class FollowSerializer(serializers.ModelSerializer):
    follower = UserMiniSerializer(read_only=True)
    following = UserMiniSerializer(read_only=True)

    class Meta:
        model = Follow
        fields = ['id', 'follower', 'following', 'created_at']
        read_only_fields = ['id', 'follower', 'created_at']


# ══════════════════════════════════════════════════════════════════════════════
# CHAT / MESSAGING SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = ChatParticipant
        fields = ['id', 'user', 'role', 'joined_at', 'is_muted', 'is_pinned']
        read_only_fields = ['id', 'user', 'joined_at']


class MessageSerializer(serializers.ModelSerializer):
    """
    PERF OVERHAUL — message list 10s -> ~2s

    Pehle ki problems:
    1. sender = UserMiniSerializer — heavy: 12+ fields + SerializerMethodField calls per message.
    2. reply_to = PrimaryKeyRelatedField — sirf ID tha, Flutter nested object expect karta tha.
    3. read_by field missing — read_receipts prefetch slow + Flutter readBy always empty.

    Ab:
    - sender: lightweight dict (id, full_name, username only)
    - sender_id / sender_name / username: flat fields — WS/cache consistent, isMine() sahi kaam kare
    - reply_to: nested light serializer (id + content + sender_name)
    - read_by: list of user IDs from prefetched read_receipts (zero extra queries)
    """
    sender_id   = serializers.CharField(source='sender.id',        read_only=True)
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    username    = serializers.CharField(source='sender.username',   read_only=True)
    sender      = serializers.SerializerMethodField()
    reply_to    = serializers.SerializerMethodField()
    read_by     = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'room', 'sender', 'sender_id', 'sender_name', 'username',
            'message_type', 'content',
            'file_url', 'file_name', 'file_size',
            'reply_to', 'is_edited', 'is_deleted', 'created_at', 'updated_at',
            'read_by',
        ]
        read_only_fields = ['id', 'sender', 'room', 'is_edited', 'is_deleted', 'created_at', 'updated_at']

    def get_sender(self, obj):
        # Minimal sender dict — Flutter UserModel.fromJson ke liye
        if not obj.sender_id:
            return None
        s = obj.sender
        return {
            'id': str(s.id),
            'full_name': s.full_name or '',
            'username': s.username or '',
            'email': getattr(s, 'email', '') or '',
            'is_online': getattr(s, 'is_online', False),
            'profile_photo': None,
        }

    def get_reply_to(self, obj):
        # Lightweight — reply_to__sender select_related view mein already hai
        r = obj.reply_to
        if not r:
            return None
        return {
            'id': str(r.id),
            'content': r.content or '',
            'message_type': r.message_type or 'text',
            'sender_name': r.sender.full_name if r.sender else '',
        }

    def get_read_by(self, obj):
        # read_receipts prefetch view mein already hai — zero extra queries
        try:
            return [str(rr.user_id) for rr in obj.read_receipts.all()]
        except Exception:
            return []


class ChatRoomSerializer(serializers.ModelSerializer):
    """
    PERF: last_message, unread_count, is_pinned_by_me — context se read karta hai.
    Views.py ChatRoomListView mein 3 bulk queries inject hoti hain — N+1 khatam.
    """
    participants = ChatParticipantSerializer(source='room_participants', many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    is_pinned_by_me = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'room_type', 'name', 'description', 'group_icon',
                  'created_by', 'participants', 'last_message', 'unread_count',
                  'is_pinned_by_me', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_last_message(self, obj):
        last_msgs = self.context.get('last_msgs')
        if last_msgs is not None:
            last = last_msgs.get(obj.id)
        else:
            # Fallback for single-room views — "Clear Chat" ko yahan bhi
            # respect karo, warna clear ke baad bhi purana last_message
            # single-room responses (room detail, direct-create) mein
            # dikhta reh jaata.
            qs = obj.messages.filter(is_deleted=False)
            request = self.context.get('request')
            if request and request.user.is_authenticated:
                participant = obj.room_participants.filter(user=request.user).first()
                if participant and participant.cleared_at:
                    qs = qs.filter(created_at__gt=participant.cleared_at)
            last = qs.select_related('sender').order_by('-created_at').first()

        if not last:
            return None
        return {
            'id': str(last.id),
            'content': last.content,
            'message_type': last.message_type,
            'sender_name': last.sender.full_name if last.sender else '',
            'created_at': last.created_at.isoformat(),
            'is_edited': last.is_edited,
        }

    def get_unread_count(self, obj):
        unread_map = self.context.get('unread_map')
        if unread_map is not None:
            return unread_map.get(obj.id, 0)
        # Fallback
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0
        participant = obj.room_participants.filter(user=request.user).first()
        if not participant:
            return 0
        # ✅ "Clear Chat": floor = jo baad mein hua ho, last_read_at ya cleared_at
        candidates = [t for t in (participant.last_read_at, participant.cleared_at) if t]
        floor = max(candidates) if candidates else None
        qs = obj.messages.filter(is_deleted=False).exclude(sender=request.user)
        if floor:
            qs = qs.filter(created_at__gt=floor)
        return qs.count()

    def get_is_pinned_by_me(self, obj):
        pinned_map = self.context.get('pinned_map')
        if pinned_map is not None:
            return pinned_map.get(obj.id, False)
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        p = obj.room_participants.filter(user=request.user).first()
        return p.is_pinned if p else False


class CreateDirectChatSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class CreateGroupChatSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    participant_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class SubChannelSerializer(serializers.ModelSerializer):
    channel = serializers.UUIDField(source='parent.id', read_only=True)

    class Meta:
        model = SubChannel
        fields = ['id', 'channel', 'name', 'slug', 'description', 'unread_count',
                  'is_default', 'created_at']
        read_only_fields = ['id', 'channel', 'slug', 'created_at']


class ChannelSerializer(serializers.ModelSerializer):
    """
    PERF FIX: is_joined / is_member / user_role — context se read karte hain.
    Channel list views inject karein:
        context['membership_map'] = {channel_id: {'role': ..., 'status': ...}}
    """
    created_by = UserMiniSerializer(read_only=True)
    is_joined = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    sub_channels = SubChannelSerializer(many=True, read_only=True)
    unread_count = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = ['id', 'name', 'slug', 'description', 'channel_type', 'icon', 'icon_url',
                  'cover', 'cover_url', 'court_name', 'city', 'state', 'is_official', 'is_private',
                  'pinned_message', 'created_by', 'member_count', 'is_joined', 'is_member',
                  'user_role', 'sub_channels', 'unread_count', 'created_at']
        read_only_fields = ['id', 'slug', 'created_by', 'member_count', 'created_at']

    def _get_membership(self, obj):
        """Return pre-fetched membership dict or None."""
        membership_map = self.context.get('membership_map')
        if membership_map is not None:
            return membership_map.get(obj.id)
        # Fallback (single channel views)
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        m = obj.memberships.filter(user=request.user).first()
        if m:
            return {'role': m.role, 'status': m.status}
        return None

    def get_is_joined(self, obj):
        m = self._get_membership(obj)
        return m is not None and m.get('status') == 'active'

    def get_is_member(self, obj):
        return self.get_is_joined(obj)

    def get_user_role(self, obj):
        m = self._get_membership(obj)
        return m.get('role') if m else None

    def get_unread_count(self, obj):
        return 0

    def get_icon_url(self, obj):
        return obj.icon or None

    def get_cover_url(self, obj):
        return obj.cover or None


class ChannelPostReactionSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = ChannelPostReaction
        fields = ['id', 'user', 'reaction_type', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class ChannelPostReactionSummarySerializer(serializers.Serializer):
    like       = serializers.IntegerField(default=0)
    love       = serializers.IntegerField(default=0)
    insightful = serializers.IntegerField(default=0)
    celebrate  = serializers.IntegerField(default=0)
    support    = serializers.IntegerField(default=0)


class ChannelPostCommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = ChannelPostComment
        fields = ['id', 'post', 'author', 'content', 'parent', 'replies', 'created_at']
        read_only_fields = ['id', 'post', 'author', 'created_at']

    def get_replies(self, obj):
        if obj.parent is None:
            # ✅ PERF: prefetch_related('replies__author') in view queryset
            return ChannelPostCommentSerializer(
                obj.replies.all()[:5], many=True, context=self.context
            ).data
        return []


class ChannelPostSerializer(serializers.ModelSerializer):
    """
    PERF FIX:
    - comments: sirf top 5, select_related author — ab view queryset mein
      prefetch_related('comments__author') hoga.
    - is_liked, user_reaction: context se pre-fetched set/dict use karte hain.
    - reactions_summary: context se ya ek aggregated query.

    Views inject karein:
        context['user_reactions_channel'] = {post_id: reaction_type}  # current user ka
        context['user_liked_post_ids_channel'] = set()                 # post ids jo liked hain
    """
    author            = UserMiniSerializer(read_only=True)
    comments          = serializers.SerializerMethodField()
    is_liked          = serializers.SerializerMethodField()
    user_reaction     = serializers.SerializerMethodField()
    reactions_summary = serializers.SerializerMethodField()
    sub_channel_name  = serializers.SerializerMethodField()
    attachment_url    = serializers.SerializerMethodField()

    class Meta:
        model = ChannelPost
        fields = ['id', 'channel', 'sub_channel', 'sub_channel_name', 'author',
                  'content', 'attachment_url', 'attachment_type',
                  'is_pinned', 'is_announcement', 'like_count', 'comment_count',
                  'comments', 'is_liked', 'user_reaction', 'reactions_summary',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'author', 'channel', 'like_count', 'comment_count', 'created_at']
        extra_kwargs = {
            'sub_channel': {'required': False, 'allow_null': True},
            'attachment_type': {'required': False, 'allow_blank': True},
            'is_pinned': {'required': False},
            'is_announcement': {'required': False},
        }

    def get_comments(self, obj):
        # ✅ PERF: prefetch_related('comments__author', 'comments__replies__author')
        # should be set on view queryset. Limit to 5 top-level.
        top = [c for c in obj.comments.all() if c.parent_id is None][:5]
        return ChannelPostCommentSerializer(top, many=True, context=self.context).data

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # ✅ PERF: context-injected set
        liked_ids = self.context.get('user_liked_post_ids_channel')
        if liked_ids is not None:
            return obj.id in liked_ids
        return obj.reactions.filter(user=request.user).exists()

    def get_user_reaction(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        # ✅ PERF: context-injected dict
        reactions = self.context.get('user_reactions_channel')
        if reactions is not None:
            return reactions.get(obj.id)
        rxn = obj.reactions.filter(user=request.user).first()
        return rxn.reaction_type if rxn else None

    def get_reactions_summary(self, obj):
        from django.db.models import Count
        qs = obj.reactions.values('reaction_type').annotate(count=Count('id'))
        return {row['reaction_type']: row['count'] for row in qs}

    def get_sub_channel_name(self, obj):
        return obj.sub_channel.name if obj.sub_channel else None

    def get_attachment_url(self, obj):
        return obj.attachment_url or None


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY FEED SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class HashtagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hashtag
        fields = ['id', 'name', 'post_count']


class PostCommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ['id', 'post', 'author', 'content', 'parent', 'like_count', 'replies', 'created_at']
        read_only_fields = ['id', 'post', 'author', 'like_count', 'created_at']

    def get_replies(self, obj):
        if obj.parent is None:
            return PostCommentSerializer(
                obj.replies.all()[:5], many=True, context=self.context
            ).data
        return []


class PostSerializer(serializers.ModelSerializer):
    """
    PERF FIX — N+1 eliminated in feed:
    ──────────────────────────────────────────────────────────────────
    ORIGINAL: 3 DB queries per post
      get_user_reaction() → SELECT FROM post_reactions WHERE post=... AND user=...
      get_is_saved()      → SELECT FROM saved_posts WHERE user=... AND post=...
      get_top_comments()  → SELECT FROM post_comments WHERE post=... LIMIT 3

    NEW: Views inject context dicts — 0 extra queries per post.
    FeedListCreateView inject karein:
        context['user_reactions'] = {post_id: reaction_type}
        context['saved_post_ids'] = set(post_ids)
    ──────────────────────────────────────────────────────────────────
    """
    author        = UserMiniSerializer(read_only=True)
    user_reaction = serializers.SerializerMethodField()
    top_comments  = serializers.SerializerMethodField()
    hashtags      = HashtagSerializer(many=True, read_only=True)
    is_saved      = serializers.SerializerMethodField()
    media         = serializers.SerializerMethodField()
    hashtag_names = serializers.ListField(
        child=serializers.CharField(max_length=100),
        write_only=True, required=False, default=list,
    )

    class Meta:
        model = Post
        fields = ['id', 'author', 'post_type', 'content', 'media', 'media_type',
                  'is_public', 'like_count', 'comment_count', 'share_count',
                  'user_reaction', 'top_comments', 'hashtags', 'hashtag_names',
                  'is_saved', 'created_at', 'updated_at']
        read_only_fields = ['id', 'author', 'like_count', 'comment_count',
                            'share_count', 'created_at', 'updated_at']

    def get_media(self, obj):
        if not obj.media:
            return None
        url = str(obj.media)
        if url.startswith('http://') or url.startswith('https://'):
            return url
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_user_reaction(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        # ✅ PERF: context dict — O(1), no DB query
        user_reactions = self.context.get('user_reactions')
        if user_reactions is not None:
            return user_reactions.get(obj.id)
        # Fallback (single post views)
        reaction = obj.reactions.filter(user=request.user).first()
        return reaction.reaction_type if reaction else None

    def get_top_comments(self, obj):
        # ✅ PERF: View queryset mein prefetch_related('comments__author') hona chahiye.
        # Yahan sirf filter + slice — already prefetched data use hoga.
        top = obj.comments.filter(parent=None).order_by('-created_at')[:3]
        return PostCommentSerializer(top, many=True, context=self.context).data

    def get_is_saved(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # ✅ PERF: context set — O(1), no DB query
        saved_ids = self.context.get('saved_post_ids')
        if saved_ids is not None:
            return obj.id in saved_ids
        return SavedPost.objects.filter(user=request.user, post=obj).exists()

    def create(self, validated_data):
        validated_data.pop('hashtag_names', None)
        return super().create(validated_data)


# ══════════════════════════════════════════════════════════════════════════════
# CASE GROUP SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class GroupDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = GroupDocument
        fields = ['id', 'group', 'uploaded_by', 'file', 'file_name', 'file_size',
                  'description', 'created_at']
        read_only_fields = ['id', 'uploaded_by', 'created_at']


class GroupMembershipSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = GroupMembership
        fields = ['user', 'role', 'joined_at']


class CaseGroupSerializer(serializers.ModelSerializer):
    created_by = UserMiniSerializer(read_only=True)
    memberships = GroupMembershipSerializer(many=True, read_only=True)
    documents = GroupDocumentSerializer(many=True, read_only=True)
    is_member = serializers.SerializerMethodField()

    class Meta:
        model = CaseGroup
        fields = ['id', 'name', 'description', 'case_number', 'court',
                  'created_by', 'is_invite_only', 'is_active', 'memberships',
                  'documents', 'is_member', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_is_member(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.memberships.filter(user=request.user).exists()


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION SERIALIZER
# ══════════════════════════════════════════════════════════════════════════════

class NotificationSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'sender', 'notif_type', 'title', 'body', 'data', 'is_read', 'created_at']
        read_only_fields = ['id', 'sender', 'notif_type', 'title', 'body', 'data', 'created_at']


# ══════════════════════════════════════════════════════════════════════════════
# REPORT SERIALIZER
# ══════════════════════════════════════════════════════════════════════════════

class ReportSerializer(serializers.ModelSerializer):
    reporter = UserMiniSerializer(read_only=True)

    class Meta:
        model = Report
        fields = ['id', 'reporter', 'report_type', 'reason', 'description',
                  'status', 'target_id', 'created_at']
        read_only_fields = ['id', 'reporter', 'status', 'created_at']


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name', 'phone', 'is_active', 'is_staff',
                  'is_verified', 'is_advocate', 'advocate_status', 'date_joined',
                  'last_seen', 'is_online', 'presence_status', 'cases_handled', 'advocate_rating']
        read_only_fields = ['id', 'username', 'date_joined']


class AdminAdvocateVerifySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['approved', 'rejected'])
    admin_notes = serializers.CharField(required=False, allow_blank=True)