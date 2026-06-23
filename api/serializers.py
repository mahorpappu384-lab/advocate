"""
Advocate App - All Serializers
UI Features aligned with LegalConnect screenshots.
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
    """Minimal user info — embedded in posts, messages, channels."""
    
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
            # Privacy — advocate_detail_screen message button check ke liye
            'who_can_message',
            'who_can_see_profile',
        ]

    def get_profile_photo(self, obj):
        try:
            if obj.advocate_profile.profile_photo:
                return obj.advocate_profile.profile_photo
        except AdvocateProfile.DoesNotExist:
            pass

        return None

    def get_is_advocate_verified(self, obj):
        return obj.is_advocate and obj.advocate_status == 'approved'


class UserProfileSerializer(serializers.ModelSerializer):
    """Full user profile — /api/users/me/ and /api/users/<id>/"""
    # AdvocateProfile se liya gaya — Flutter onboarding redirect ke liye
    onboarding_complete = serializers.SerializerMethodField()

    def get_onboarding_complete(self, obj):
        try:
            return obj.advocate_profile.onboarding_complete
        except AdvocateProfile.DoesNotExist:
            return False

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'full_name', 'phone',
            'is_verified', 'is_advocate', 'advocate_status',
            'date_joined', 'is_online', 'last_seen',
            # Profile screen: presence status
            'presence_status',
            # Profile screen: appearance
            'theme', 'accent_color',
            # Profile screen: notification toggles
            'notif_messages', 'notif_group_mentions', 'notif_stories', 'notif_calls',
            # Profile screen: privacy settings
            'privacy_read_receipts', 'privacy_last_seen', 'privacy_online_status',
            # Who Can — granular access controls
            'who_can_message', 'who_can_see_profile',
            # Home stats
            'cases_handled', 'advocate_rating',
            # Onboarding check — AdvocateProfile se computed
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
    user = UserMiniSerializer(read_only=True)
    education = AdvocateEducationSerializer(many=True, read_only=True)
    experience = AdvocateExperienceSerializer(many=True, read_only=True)
    achievements = AdvocateAchievementSerializer(many=True, read_only=True)
    is_connected = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    connection_status = serializers.SerializerMethodField()
    # Real-time counts — cached fields pe rely mat karo
    post_count = serializers.SerializerMethodField()
    connection_count = serializers.SerializerMethodField()

    def get_post_count(self, obj):
        return Post.objects.filter(author=obj.user).count()

    def get_connection_count(self, obj):
        """
        Direct DB se real count — cached field desync hone pe bhi sahi return karta hai.
        Side effect: cached field bhi update karta hai taaki future reads fast hon.
        """
        real_count = Connection.objects.filter(
            Q(sender=obj.user) | Q(receiver=obj.user),
            status='accepted'
        ).count()
        # Sync cache if drifted
        if obj.connection_count != real_count:
            AdvocateProfile.objects.filter(pk=obj.pk).update(connection_count=real_count)
        return real_count

    class Meta:
        model = AdvocateProfile
        fields = '__all__'
        read_only_fields = ['user', 'connection_count', 'follower_count',
                            'post_count', 'media_count', 'group_count', 'message_count']

    def get_is_connected(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Connection.objects.filter(
            sender__in=[request.user, obj.user],
            receiver__in=[request.user, obj.user],
            status='accepted'
        ).exists()

    def get_is_following(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return Follow.objects.filter(follower=request.user, following=obj.user).exists()

    def get_connection_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        conn = Connection.objects.filter(
            sender__in=[request.user, obj.user],
            receiver__in=[request.user, obj.user],
        ).first()
        if conn:
            return {'status': conn.status, 'is_sender': conn.sender == request.user}
        return None


class AdvocateVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateProfile
        fields = ['bar_council_id', 'bar_council_id_image', 'enrollment_number',
                  'enrollment_year', 'state_bar_council']


# ══════════════════════════════════════════════════════════════════════════════
# HOME SCREEN SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class HearingSerializer(serializers.ModelSerializer):
    """Home screen: Today's Hearings list."""
    class Meta:
        model = Hearing
        fields = ['id', 'case_title', 'case_number', 'court', 'court_room',
                  'hearing_time', 'hearing_date', 'hearing_type', 'notes',
                  'is_completed', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class LegalUpdateSerializer(serializers.ModelSerializer):
    """Home screen: Recent Updates list."""
    class Meta:
        model = LegalUpdate
        fields = ['id', 'title', 'summary', 'source_url', 'urgency', 'created_at']
        read_only_fields = ['id', 'created_at']


class HomeDashboardSerializer(serializers.Serializer):
    """
    Home screen: Combined dashboard response.
    GET /api/home/dashboard/
    Returns stats, today's hearings, recent updates.
    """
    # Stats cards
    cases_handled = serializers.IntegerField()
    connections = serializers.IntegerField()
    hearings_today = serializers.IntegerField()
    advocate_rating = serializers.DecimalField(max_digits=3, decimal_places=1)

    # Lists
    todays_hearings = HearingSerializer(many=True)
    recent_updates = LegalUpdateSerializer(many=True)


# ══════════════════════════════════════════════════════════════════════════════
# NETWORKING SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    receiver = UserMiniSerializer(read_only=True)

    # Flutter ke liye shortcut fields — dono tabs (Sent + Pending) mein use hote hain
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
            # Shortcut fields
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
        try:
            return obj.sender.advocate_profile.profile_photo or None
        except Exception:
            return None

    def get_receiver_photo(self, obj):
        try:
            return obj.receiver.advocate_profile.profile_photo or None
        except Exception:
            return None

    def get_sender_court(self, obj):
        try:
            return obj.sender.advocate_profile.primary_court or ''
        except Exception:
            return ''

    def get_receiver_court(self, obj):
        try:
            return obj.receiver.advocate_profile.primary_court or ''
        except Exception:
            return ''


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
# Chat screen: pinned chats, All/Direct/Groups/Pinned tabs, unread badges
# ══════════════════════════════════════════════════════════════════════════════

class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = ChatParticipant
        fields = ['user', 'role', 'joined_at', 'last_read_at', 'is_muted', 'is_pinned']


class MessageSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    reply_to_preview = serializers.SerializerMethodField()
    read_by_count = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    read_by = serializers.SerializerMethodField()

    # Flutter MessageModel.fromJson ke liye flat fields —
    # sender object ke saath yeh bhi chahiye taaki isMine() kaam kare
    sender_id   = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    username    = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'room', 'sender', 'sender_id', 'sender_name', 'username',
                  'message_type', 'content', 'file',
                  'file_name', 'file_size', 'reply_to', 'reply_to_preview',
                  'is_edited', 'is_deleted', 'created_at', 'updated_at',
                  'read_by_count', 'is_read', 'file_url', 'read_by']
        read_only_fields = ['id', 'sender', 'is_edited', 'created_at', 'updated_at']

    def get_sender_id(self, obj):
        return str(obj.sender_id) if obj.sender_id else None

    def get_sender_name(self, obj):
        if obj.sender:
            return obj.sender.full_name or obj.sender.username or ''
        return ''

    def get_username(self, obj):
        return obj.sender.username if obj.sender else ''

    def get_reply_to_preview(self, obj):
        if obj.reply_to and not obj.reply_to.is_deleted:
            return {
                'id': str(obj.reply_to.id),
                'sender': obj.reply_to.sender.full_name if obj.reply_to.sender else 'Unknown',
                'content': obj.reply_to.content[:100],
                'message_type': obj.reply_to.message_type,
            }
        return None

    def get_read_by_count(self, obj):
        return obj.read_receipts.count()

    def get_is_read(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.read_receipts.filter(user=request.user).exists()
        return False

    def get_read_by(self, obj):
        """Double-tick ke liye: jo users ne message padha unke UUID strings."""
        return [str(r.user_id) for r in obj.read_receipts.all()]


class ChatRoomSerializer(serializers.ModelSerializer):
    participants = ChatParticipantSerializer(source='room_participants', many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    # Chat screen: is this chat pinned by the current user
    is_pinned_by_me = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'room_type', 'name', 'description', 'group_icon',
                  'created_by', 'participants', 'last_message', 'unread_count',
                  'is_pinned_by_me', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_last_message(self, obj):
        last = obj.messages.filter(is_deleted=False).last()
        if last:
            return {
                'id': str(last.id),
                'content': last.content if last.message_type == 'text' else f'[{last.message_type}]',
                'sender_name': last.sender.full_name if last.sender else 'Unknown',
                'sender_username': last.sender.username if last.sender else '',
                'created_at': last.created_at,
                'message_type': last.message_type,
                'is_edited': last.is_edited,
            }
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0
        participant = obj.room_participants.filter(user=request.user).first()
        if not participant:
            return 0
        last_read = participant.last_read_at
        if last_read:
            return obj.messages.filter(created_at__gt=last_read, is_deleted=False).exclude(sender=request.user).count()
        return obj.messages.filter(is_deleted=False).exclude(sender=request.user).count()

    def get_is_pinned_by_me(self, obj):
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
# Channel screen: sub-channels, pinned posts, react+reply
# ══════════════════════════════════════════════════════════════════════════════

class SubChannelSerializer(serializers.ModelSerializer):
    """Channel screen: sub-channel list inside a parent channel."""
    # Flutter SubChannelModel expects 'channel' field (parent channel UUID)
    channel = serializers.UUIDField(source='parent.id', read_only=True)
    # FIXED: is_default ab direct model field hai — computed SerializerMethodField nahi
    # is_default writable hai taaki create/update mein pass ho sake

    class Meta:
        model = SubChannel
        fields = ['id', 'channel', 'name', 'slug', 'description', 'unread_count',
                  'is_default', 'created_at']
        read_only_fields = ['id', 'channel', 'slug', 'created_at']


class ChannelSerializer(serializers.ModelSerializer):
    created_by = UserMiniSerializer(read_only=True)
    # Flutter ChannelModel uses 'is_joined' — keep both for compatibility
    is_joined = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()   # backward-compat alias
    user_role = serializers.SerializerMethodField()
    sub_channels = SubChannelSerializer(many=True, read_only=True)
    unread_count = serializers.SerializerMethodField()
    # icon/cover — return full URL when stored as R2 URL field or ImageField
    icon_url = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = ['id', 'name', 'slug', 'description', 'channel_type', 'icon', 'icon_url',
                  'cover', 'cover_url', 'court_name', 'city', 'state', 'is_official', 'is_private',
                  'pinned_message', 'created_by', 'member_count', 'is_joined', 'is_member',
                  'user_role', 'sub_channels', 'unread_count', 'created_at']
        read_only_fields = ['id', 'slug', 'created_by', 'member_count', 'created_at']

    def get_is_joined(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # Only active memberships — pending join requests should NOT count
        return obj.memberships.filter(user=request.user, status='active').exists()

    def get_is_member(self, obj):
        return self.get_is_joined(obj)

    def get_user_role(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None

    def get_unread_count(self, obj):
        # Placeholder — can be computed from last read tracking later
        return 0

    def get_icon_url(self, obj):
        """icon ab URLField hai — seedha return karo (ImageField logic hatao)."""
        return obj.icon or None

    def get_cover_url(self, obj):
        """cover ab URLField hai — seedha return karo."""
        return obj.cover or None


class ChannelPostReactionSerializer(serializers.ModelSerializer):
    """Telegram-style per-type reaction summary for a channel post."""
    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = ChannelPostReaction
        fields = ['id', 'user', 'reaction_type', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class ChannelPostReactionSummarySerializer(serializers.Serializer):
    """
    Aggregated reaction counts — Telegram style.
    e.g. { "like": 5, "love": 2, "insightful": 3, ... }
    """
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
            return ChannelPostCommentSerializer(
                obj.replies.all()[:5], many=True, context=self.context
            ).data
        return []


class ChannelPostSerializer(serializers.ModelSerializer):
    author           = UserMiniSerializer(read_only=True)
    comments         = ChannelPostCommentSerializer(many=True, read_only=True)
    is_liked         = serializers.SerializerMethodField()
    user_reaction    = serializers.SerializerMethodField()   # Current user ka reaction type
    reactions_summary = serializers.SerializerMethodField()  # Telegram-style counts
    sub_channel_name = serializers.SerializerMethodField()
    attachment_url   = serializers.SerializerMethodField()

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

    def get_is_liked(self, obj):
        """Backward compat — True if user has ANY reaction on this post."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.reactions.filter(user=request.user).exists()

    def get_user_reaction(self, obj):
        """Current user ka reaction type — None if no reaction."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        rxn = obj.reactions.filter(user=request.user).first()
        return rxn.reaction_type if rxn else None

    def get_reactions_summary(self, obj):
        """
        Telegram-style per-type counts.
        Returns only types that have at least 1 reaction.
        e.g. { "like": 5, "love": 2 }
        """
        from django.db.models import Count
        qs = obj.reactions.values('reaction_type').annotate(count=Count('id'))
        return {row['reaction_type']: row['count'] for row in qs}

    def get_sub_channel_name(self, obj):
        return obj.sub_channel.name if obj.sub_channel else None

    def get_attachment_url(self, obj):
        """Return R2 URL stored in attachment_url field."""
        return obj.attachment_url or None


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY FEED SERIALIZERS
# Feed screen: hashtags, trending, save/share, post types
# ══════════════════════════════════════════════════════════════════════════════

class HashtagSerializer(serializers.ModelSerializer):
    """Feed screen: Trending Now section."""
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
    author        = UserMiniSerializer(read_only=True)
    user_reaction = serializers.SerializerMethodField()
    top_comments  = serializers.SerializerMethodField()
    hashtags      = HashtagSerializer(many=True, read_only=True)
    is_saved      = serializers.SerializerMethodField()
    # R2 URL ya local file — dono handle karta hai
    media         = serializers.SerializerMethodField()
    # Raw hashtag input for creating posts
    # Flutter 'hashtags' key bhejta hai — perform_create dono keys handle karta hai
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
        """
        R2 direct upload flow:
          - Flutter ne pehle Cloudflare R2 pe file upload kiya
          - Backend ko sirf URL mila, koi file bytes nahi
          - URLField mein full https:// URL store hota hai → seedha return karo

        Legacy FileField flow (purane records ke liye fallback):
          - File Django ke upload_to='post_media/' mein save thi
          - Relative path hoga → request se absolute URL banao
        """
        if not obj.media:
            return None

        url = str(obj.media)

        # R2 ya koi bhi absolute URL — seedha return karo
        if url.startswith('http://') or url.startswith('https://'):
            return url

        # Local file fallback (purane records)
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(url)

        return url

    def get_user_reaction(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        reaction = obj.reactions.filter(user=request.user).first()
        return reaction.reaction_type if reaction else None

    def get_top_comments(self, obj):
        top = obj.comments.filter(parent=None).order_by('-created_at')[:3]
        return PostCommentSerializer(top, many=True, context=self.context).data

    def get_is_saved(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return SavedPost.objects.filter(user=request.user, post=obj).exists()

    def create(self, validated_data):
        # hashtag_names write_only field hai — Post model mein koi column nahi
        # Pop karo warna Post.objects.create() TypeError deta hai
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