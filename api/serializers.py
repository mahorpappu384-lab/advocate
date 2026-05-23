"""
Advocate App - All Serializers
UI Features aligned with LegalConnect screenshots.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    AdvocateProfile, AdvocateEducation, AdvocateExperience, AdvocateAchievement,
    Connection, Follow, OTP,
    ChatRoom, ChatParticipant, Message, MessageReadReceipt,
    Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment, ChannelPostLike,
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
        fields = ['id', 'full_name', 'username', 'email', 'is_advocate',
                  'advocate_status', 'profile_photo', 'is_advocate_verified',
                  'presence_status', 'is_online']

    def get_profile_photo(self, obj):
        try:
            request = self.context.get('request')
            if obj.advocate_profile.profile_photo:
                if request:
                    return request.build_absolute_uri(obj.advocate_profile.profile_photo.url)
                return obj.advocate_profile.profile_photo.url
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

    class Meta:
        model = Connection
        fields = ['id', 'sender', 'receiver', 'status', 'message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'sender', 'status', 'created_at', 'updated_at']


class ConnectionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = ['receiver', 'message']


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

    class Meta:
        model = Message
        fields = ['id', 'room', 'sender', 'message_type', 'content', 'file',
                  'file_name', 'file_size', 'reply_to', 'reply_to_preview',
                  'is_edited', 'is_deleted', 'created_at', 'updated_at',
                  'read_by_count', 'is_read']
        read_only_fields = ['id', 'sender', 'is_edited', 'created_at', 'updated_at']

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
    class Meta:
        model = SubChannel
        fields = ['id', 'name', 'slug', 'description', 'unread_count', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']


class ChannelSerializer(serializers.ModelSerializer):
    created_by = UserMiniSerializer(read_only=True)
    is_member = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    sub_channels = SubChannelSerializer(many=True, read_only=True)

    class Meta:
        model = Channel
        fields = ['id', 'name', 'slug', 'description', 'channel_type', 'icon',
                  'cover', 'court_name', 'city', 'state', 'is_official', 'is_private',
                  'pinned_message', 'created_by', 'member_count', 'is_member',
                  'user_role', 'sub_channels', 'created_at']
        read_only_fields = ['id', 'slug', 'created_by', 'member_count', 'created_at']

    def get_is_member(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.memberships.filter(user=request.user).exists()

    def get_user_role(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None


class ChannelPostCommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = ChannelPostComment
        fields = ['id', 'post', 'author', 'content', 'parent', 'replies', 'created_at']
        read_only_fields = ['id', 'author', 'created_at']

    def get_replies(self, obj):
        if obj.parent is None:
            return ChannelPostCommentSerializer(
                obj.replies.all()[:5], many=True, context=self.context
            ).data
        return []


class ChannelPostSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    comments = ChannelPostCommentSerializer(many=True, read_only=True)
    is_liked = serializers.SerializerMethodField()
    # Channel screen: which sub-channel this post belongs to
    sub_channel_name = serializers.SerializerMethodField()

    class Meta:
        model = ChannelPost
        fields = ['id', 'channel', 'sub_channel', 'sub_channel_name', 'author',
                  'content', 'attachment', 'attachment_type',
                  'is_pinned', 'is_announcement', 'like_count', 'comment_count',
                  'comments', 'is_liked', 'created_at', 'updated_at']
        read_only_fields = ['id', 'author', 'like_count', 'comment_count', 'created_at']

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.likes.filter(user=request.user).exists()

    def get_sub_channel_name(self, obj):
        return obj.sub_channel.name if obj.sub_channel else None


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
    author = UserMiniSerializer(read_only=True)
    user_reaction = serializers.SerializerMethodField()
    top_comments = serializers.SerializerMethodField()
    hashtags = HashtagSerializer(many=True, read_only=True)
    # Feed screen: has the current user saved this post?
    is_saved = serializers.SerializerMethodField()
    # Raw hashtag input for creating posts
    hashtag_names = serializers.ListField(
        child=serializers.CharField(max_length=100),
        write_only=True, required=False
    )

    class Meta:
        model = Post
        fields = ['id', 'author', 'post_type', 'content', 'media', 'media_type',
                  'is_public', 'like_count', 'comment_count', 'share_count',
                  'user_reaction', 'top_comments', 'hashtags', 'hashtag_names',
                  'is_saved', 'created_at', 'updated_at']
        read_only_fields = ['id', 'author', 'like_count', 'comment_count',
                            'share_count', 'created_at', 'updated_at']

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