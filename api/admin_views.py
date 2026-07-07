"""
admin_views.py
══════════════════════════════════════════════════════════════════════════════
PERFECT SUPER-ADMIN BACKEND — pure app ko A-to-Z monitor + manage karne ke liye.

Isme kya milta hai:
  1. AdminBootstrapCreateView  → API key se naya SUPERUSER create karo (no shell needed)
  2. AdminLoginView            → sirf superuser accounts ke liye JWT login
  3. AdminDashboardStatsView   → poore platform ka ek single stats snapshot
  4. Har model ke liye List + Retrieve/Update/Delete views (monitor + manage):
       Users, AdvocateProfile (+education/experience/achievements),
       Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment,
       Post, PostComment, Hashtag, Report, Connection, Follow,
       ChatRoom, Message, CaseGroup, GroupMembership, GroupDocument,
       Notification, Hearing, LegalUpdate, Story, OTP
  5. Moderation actions: ban/unban, set-staff, set-superuser, reset-password,
     verify/reject advocate, resolve report.

SETUP REQUIRED (settings.py / .env mein):
    ADMIN_BOOTSTRAP_API_KEY = "a-long-random-secret-string"

USAGE (bootstrap your first admin):
    curl -X POST https://yourdomain.com/api/admin/bootstrap/ \
         -H "X-Admin-Api-Key: <ADMIN_BOOTSTRAP_API_KEY>" \
         -H "Content-Type: application/json" \
         -d '{"username": "superadmin", "password": "StrongPass123", "full_name": "Super Admin"}'

    Phir usi username/password se /api/admin/login/ pe login karke JWT lo,
    aur baaki sab admin/* endpoints ko "Authorization: Bearer <access_token>" ke saath call karo.
══════════════════════════════════════════════════════════════════════════════
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, authenticate
from django.db.models import Count
from django.utils import timezone

from rest_framework import generics, status, permissions, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework_simplejwt.tokens import RefreshToken
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    AdvocateProfile, AdvocateEducation, AdvocateExperience, AdvocateAchievement,
    Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment,
    ChannelPostReaction, Hashtag, Post, PostComment, PostReaction, SavedPost,
    PostShare, Report, Connection, Follow, ChatRoom, ChatParticipant, Message,
    CaseGroup, GroupMembership, GroupDocument, Notification, Hearing,
    LegalUpdate, Story, OTP,
)
from .utils import send_verification_status_email, create_notification

User = get_user_model()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

class IsSuperUser(permissions.BasePermission):
    """
    Sirf real SUPERUSER (django is_superuser=True) ko allow karta hai.
    Normal is_staff editors is se block ho jaate hain — matlab "asli" admin hi
    yeh pura backend chala sakta hai.
    """
    message = "Access denied. Sirf super-admin account is action ko perform kar sakta hai."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )


# ══════════════════════════════════════════════════════════════════════════════
# 1) BOOTSTRAP — API KEY SE NAYA SUPERUSER BANAO
# ══════════════════════════════════════════════════════════════════════════════

class AdminBootstrapCreateView(APIView):
    """
    POST /api/admin/bootstrap/
    Header : X-Admin-Api-Key: <ADMIN_BOOTSTRAP_API_KEY>
    Body   : { "username", "password", "email"?, "full_name"?, "phone"? }

    Koi bhi login/token ki zaroorat nahi — sirf secret API key chahiye.
    Har call pe naya SUPERUSER bana sakte ho (multiple admins allowed).
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # JWT/session skip — key hi gatekeeper hai

    def post(self, request):
        real_key = getattr(settings, 'ADMIN_BOOTSTRAP_API_KEY', None)
        if not real_key:
            logger.critical("ADMIN_BOOTSTRAP_API_KEY settings/.env mein set nahi hai!")
            return Response(
                {"error": "Admin bootstrap disabled — server par ADMIN_BOOTSTRAP_API_KEY set nahi hai."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        provided_key = request.headers.get('X-Admin-Api-Key') or request.data.get('api_key')
        if not provided_key or provided_key != real_key:
            logger.warning("Admin bootstrap: invalid ya missing API key se attempt hua.")
            return Response({"error": "Invalid or missing API key."}, status=status.HTTP_403_FORBIDDEN)

        username  = (request.data.get('username') or '').strip()
        password  = request.data.get('password') or ''
        email     = (request.data.get('email') or '').strip()
        full_name = (request.data.get('full_name') or '').strip() or username
        phone     = (request.data.get('phone') or '').strip() or None

        if not username or not password:
            return Response({"error": "username aur password required hain."}, status=400)
        if len(password) < 8:
            return Response({"error": "Password kam se kam 8 characters ka hona chahiye."}, status=400)
        if User.objects.filter(username=username).exists():
            return Response({"error": f"Username '{username}' pehle se exist karta hai."}, status=400)

        user = User.objects.create_superuser(
            username=username,
            password=password,
            email=email or None,
            full_name=full_name,
            phone=phone,
        )
        logger.info(f"[ADMIN BOOTSTRAP] Naya superuser create hua: {username}")

        return Response({
            "message": f"Superuser '{username}' successfully create ho gaya.",
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
            }
        }, status=status.HTTP_201_CREATED)


# ══════════════════════════════════════════════════════════════════════════════
# 2) SUPERUSER-ONLY LOGIN
# ══════════════════════════════════════════════════════════════════════════════

class AdminLoginView(APIView):
    """
    POST /api/admin/login/
    Body: { "username", "password" }
    Sirf is_superuser=True accounts login kar sakte hain — normal user/advocate
    yahaan 403 pa jaayega, chahe password sahi ho.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''

        if not username or not password:
            return Response({"error": "username aur password required hain."}, status=400)

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_superuser:
            logger.warning(f"[ADMIN LOGIN] Non-superuser '{username}' ne admin login try kiya.")
            return Response({"error": "Aap super-admin nahi ho. Access denied."}, status=status.HTTP_403_FORBIDDEN)

        if not user.is_active:
            return Response({"error": "Yeh account deactivate/banned hai."}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        user.last_seen = timezone.now()
        user.save(update_fields=['last_seen'])

        return Response({
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "admin": {
                "id": str(user.id),
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "is_superuser": True,
            }
        })


# ══════════════════════════════════════════════════════════════════════════════
# 3) DASHBOARD — POORE PLATFORM KA A-TO-Z SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════

class AdminDashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/
    Ek hi call mein: users, advocates, channels, posts, reports, chat,
    connections, groups, hearings, stories, notifications, OTPs — sab kuch.
    """
    permission_classes = [IsSuperUser]

    def get(self, request):
        now      = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d  = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        def growth(qs, field='created_at'):
            return {
                "total":    qs.count(),
                "last_24h": qs.filter(**{f"{field}__gte": last_24h}).count(),
                "last_7d":  qs.filter(**{f"{field}__gte": last_7d}).count(),
                "last_30d": qs.filter(**{f"{field}__gte": last_30d}).count(),
            }

        users_qs = User.objects.all()

        data = {
            "generated_at": now.isoformat(),

            "users": {
                **growth(users_qs, 'date_joined'),
                "active":         users_qs.filter(is_active=True).count(),
                "banned":         users_qs.filter(is_active=False).count(),
                "online_now":     users_qs.filter(is_online=True).count(),
                "email_verified": users_qs.filter(is_verified=True).count(),
                "staff":          users_qs.filter(is_staff=True).count(),
                "superusers":     users_qs.filter(is_superuser=True).count(),
            },

            "advocates": {
                "total":    users_qs.filter(is_advocate=True).count(),
                "pending":  users_qs.filter(advocate_status='pending').count(),
                "approved": users_qs.filter(advocate_status='approved').count(),
                "rejected": users_qs.filter(advocate_status='rejected').count(),
            },

            "channels": {
                **growth(Channel.objects.all()),
                "official":     Channel.objects.filter(is_official=True).count(),
                "private":      Channel.objects.filter(is_private=True).count(),
                "sub_channels": SubChannel.objects.count(),
                "memberships":  ChannelMembership.objects.count(),
                "posts":        ChannelPost.objects.count(),
                "comments":     ChannelPostComment.objects.count(),
                "reactions":    ChannelPostReaction.objects.count(),
            },

            "feed": {
                **growth(Post.objects.all()),
                "comments":    PostComment.objects.count(),
                "reactions":   PostReaction.objects.count(),
                "hashtags":    Hashtag.objects.count(),
                "saved_posts": SavedPost.objects.count(),
                "shares":      PostShare.objects.count(),
            },

            "reports": {
                "total":     Report.objects.count(),
                "pending":   Report.objects.filter(status='pending').count(),
                "reviewed":  Report.objects.filter(status='reviewed').count(),
                "resolved":  Report.objects.filter(status='resolved').count(),
                "dismissed": Report.objects.filter(status='dismissed').count(),
                "by_type":   list(Report.objects.values('report_type').annotate(count=Count('id')).order_by('-count')),
                "by_reason": list(Report.objects.values('reason').annotate(count=Count('id')).order_by('-count')),
            },

            "networking": {
                "connections_total":    Connection.objects.count(),
                "connections_pending":  Connection.objects.filter(status='pending').count(),
                "connections_accepted": Connection.objects.filter(status='accepted').count(),
                "connections_blocked":  Connection.objects.filter(status='blocked').count(),
                "follows_total":        Follow.objects.count(),
            },

            "chat": {
                "rooms_total":  ChatRoom.objects.count(),
                "direct_rooms": ChatRoom.objects.filter(room_type='direct').count(),
                "group_rooms":  ChatRoom.objects.filter(room_type='group').count(),
                "participants": ChatParticipant.objects.count(),
                "messages":     growth(Message.objects.all()),
            },

            "case_groups": {
                "total":       CaseGroup.objects.count(),
                "active":      CaseGroup.objects.filter(is_active=True).count(),
                "memberships": GroupMembership.objects.count(),
                "documents":   GroupDocument.objects.count(),
            },

            "hearings_and_updates": {
                "hearings_total":    Hearing.objects.count(),
                "hearings_upcoming": Hearing.objects.filter(hearing_date__gte=now.date(), is_completed=False).count(),
                "legal_updates":     LegalUpdate.objects.filter(is_active=True).count(),
            },

            "stories": {
                "total":  Story.objects.count(),
                "active": Story.objects.filter(expires_at__gte=now).count(),
            },

            "notifications": {
                "total":  Notification.objects.count(),
                "unread": Notification.objects.filter(is_read=False).count(),
            },

            "otps": {
                **growth(OTP.objects.all()),
                "used": OTP.objects.filter(is_used=True).count(),
            },
        }

        return Response(data)


# ══════════════════════════════════════════════════════════════════════════════
# SERIALIZERS — Admin ke liye "poora sach" (fields='__all__' jahan safe hai)
# ══════════════════════════════════════════════════════════════════════════════

class AdminUserFullSerializer(serializers.ModelSerializer):
    """Password kabhi expose nahi hota — baaki sab kuch dikhta hai."""
    class Meta:
        model = User
        exclude = ['password']


class AdminAdvocateProfileSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_email    = serializers.CharField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.full_name', read_only=True)
    advocate_status = serializers.CharField(source='user.advocate_status', read_only=True)

    class Meta:
        model = AdvocateProfile
        fields = '__all__'


class AdminAdvocateEducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateEducation
        fields = '__all__'


class AdminAdvocateExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateExperience
        fields = '__all__'


class AdminAdvocateAchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvocateAchievement
        fields = '__all__'


class AdminChannelSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = Channel
        fields = '__all__'


class AdminSubChannelSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source='parent.name', read_only=True)

    class Meta:
        model = SubChannel
        fields = '__all__'


class AdminChannelMembershipSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = ChannelMembership
        fields = '__all__'


class AdminChannelPostSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = ChannelPost
        fields = '__all__'


class AdminChannelPostCommentSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = ChannelPostComment
        fields = '__all__'


class AdminHashtagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hashtag
        fields = '__all__'


class AdminPostSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = Post
        fields = '__all__'


class AdminPostCommentSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = PostComment
        fields = '__all__'


class AdminReportSerializer(serializers.ModelSerializer):
    reporter_username = serializers.CharField(source='reporter.username', read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True, default=None)

    class Meta:
        model = Report
        fields = '__all__'


class AdminConnectionSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    receiver_username = serializers.CharField(source='receiver.username', read_only=True)

    class Meta:
        model = Connection
        fields = '__all__'


class AdminFollowSerializer(serializers.ModelSerializer):
    follower_username = serializers.CharField(source='follower.username', read_only=True)
    following_username = serializers.CharField(source='following.username', read_only=True)

    class Meta:
        model = Follow
        fields = '__all__'


class AdminChatRoomSerializer(serializers.ModelSerializer):
    participant_count = serializers.IntegerField(source='room_participants.count', read_only=True)

    class Meta:
        model = ChatRoom
        fields = '__all__'


class AdminMessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True, default=None)

    class Meta:
        model = Message
        fields = '__all__'


class AdminCaseGroupSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = CaseGroup
        fields = '__all__'


class AdminGroupMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupMembership
        fields = '__all__'


class AdminGroupDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupDocument
        fields = '__all__'


class AdminNotificationSerializer(serializers.ModelSerializer):
    recipient_username = serializers.CharField(source='recipient.username', read_only=True)

    class Meta:
        model = Notification
        fields = '__all__'


class AdminHearingSerializer(serializers.ModelSerializer):
    advocate_username = serializers.CharField(source='advocate.username', read_only=True)

    class Meta:
        model = Hearing
        fields = '__all__'


class AdminLegalUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalUpdate
        fields = '__all__'


class AdminStorySerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = Story
        fields = '__all__'


class AdminOTPSerializer(serializers.ModelSerializer):
    """OTP ka raw code kabhi bhi pura expose nahi hota — sirf last 2 digits."""
    user_username = serializers.CharField(source='user.username', read_only=True)
    code_masked = serializers.SerializerMethodField()

    class Meta:
        model = OTP
        fields = ['id', 'user', 'user_username', 'code_masked', 'purpose',
                  'is_used', 'created_at', 'expires_at']

    def get_code_masked(self, obj):
        return f"**{obj.code[-2:]}" if obj.code else "****"


# ══════════════════════════════════════════════════════════════════════════════
# BASE CLASSES — DRY List / Retrieve-Update-Destroy views
# ══════════════════════════════════════════════════════════════════════════════

class AdminListBase(generics.ListAPIView):
    permission_classes = [IsSuperUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]


class AdminDetailBase(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsSuperUser]


# ══════════════════════════════════════════════════════════════════════════════
# 4) USERS
# ══════════════════════════════════════════════════════════════════════════════

class AdminUserListView(AdminListBase):
    """GET /api/admin/users/?search=...&is_active=true&is_advocate=true&advocate_status=pending"""
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = AdminUserFullSerializer
    search_fields = ['username', 'full_name', 'email', 'phone']
    filterset_fields = ['is_active', 'is_advocate', 'advocate_status', 'is_staff',
                         'is_superuser', 'is_online', 'is_verified']
    ordering_fields = ['date_joined', 'last_seen', 'cases_handled', 'advocate_rating']


class AdminUserDetailView(AdminDetailBase):
    """GET/PATCH/DELETE /api/admin/users/<uuid>/"""
    queryset = User.objects.all()
    serializer_class = AdminUserFullSerializer


class AdminBanUserView(APIView):
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        user = generics.get_object_or_404(User, id=pk) if hasattr(generics, 'get_object_or_404') else _get404(User, pk)
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response({"message": f"'{user.username}' ban ho gaya."})


class AdminUnbanUserView(APIView):
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        user = _get404(User, pk)
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response({"message": f"'{user.username}' unban ho gaya."})


class AdminSetStaffView(APIView):
    """POST /api/admin/users/<uuid>/set-staff/  Body: {"is_staff": true|false}"""
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        user = _get404(User, pk)
        user.is_staff = bool(request.data.get('is_staff', False))
        user.save(update_fields=['is_staff'])
        return Response({"message": f"'{user.username}' is_staff = {user.is_staff}"})


class AdminSetSuperuserView(APIView):
    """POST /api/admin/users/<uuid>/set-superuser/  Body: {"is_superuser": true|false}
    ⚠️ Bahut powerful action — sirf existing superuser hi kisi aur ko super-admin bana/hata sakta hai."""
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        user = _get404(User, pk)
        new_val = bool(request.data.get('is_superuser', False))
        if user.id == request.user.id and not new_val:
            return Response({"error": "Aap khud se apna superuser access nahi hata sakte."}, status=400)
        user.is_superuser = new_val
        user.is_staff = user.is_staff or new_val
        user.save(update_fields=['is_superuser', 'is_staff'])
        return Response({"message": f"'{user.username}' is_superuser = {user.is_superuser}"})


class AdminResetUserPasswordView(APIView):
    """POST /api/admin/users/<uuid>/reset-password/  Body: {"new_password": "..."}"""
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        user = _get404(User, pk)
        new_password = request.data.get('new_password') or ''
        if len(new_password) < 8:
            return Response({"error": "Password kam se kam 8 characters ka hona chahiye."}, status=400)
        user.set_password(new_password)
        user.save(update_fields=['password'])
        return Response({"message": f"'{user.username}' ka password reset ho gaya."})


class AdminPendingVerificationsView(AdminListBase):
    """GET /api/admin/verifications/ — pending advocate verifications"""
    serializer_class = AdminUserFullSerializer
    search_fields = ['username', 'full_name', 'email']

    def get_queryset(self):
        return User.objects.filter(advocate_status='pending').select_related('advocate_profile').order_by('-date_joined')


class AdminVerifyAdvocateView(APIView):
    """POST /api/admin/verifications/<uuid>/decide/  Body: {"status": "approved"|"rejected", "admin_notes": "..."}"""
    permission_classes = [IsSuperUser]

    def post(self, request, user_id):
        user = _get404(User, user_id)
        new_status = request.data.get('status')
        notes = request.data.get('admin_notes', '')

        if new_status not in ('approved', 'rejected'):
            return Response({"error": "status must be 'approved' or 'rejected'."}, status=400)

        user.advocate_status = new_status
        user.save(update_fields=['advocate_status'])
        send_verification_status_email(user, new_status, notes)

        notif_type = 'verification_approved' if new_status == 'approved' else 'verification_rejected'
        title = '✅ Verification Approved!' if new_status == 'approved' else 'Verification Update'
        body = "Your advocate profile is verified!" if new_status == 'approved' else f"Not approved: {notes}"
        create_notification(recipient=user, notif_type=notif_type, title=title, body=body)

        return Response({"message": f"Advocate {new_status}.", "user_id": str(user.id), "status": new_status})


# ══════════════════════════════════════════════════════════════════════════════
# 5) ADVOCATE PROFILE + EDUCATION/EXPERIENCE/ACHIEVEMENTS
# ══════════════════════════════════════════════════════════════════════════════

class AdminAdvocateProfileListView(AdminListBase):
    queryset = AdvocateProfile.objects.select_related('user').all().order_by('-created_at')
    serializer_class = AdminAdvocateProfileSerializer
    search_fields = ['user__username', 'user__full_name', 'user__email', 'city', 'state', 'bar_council_id']
    filterset_fields = ['city', 'state', 'is_verified', 'is_public', 'onboarding_complete']
    ordering_fields = ['created_at', 'connection_count', 'years_of_experience']


class AdminAdvocateProfileDetailView(AdminDetailBase):
    queryset = AdvocateProfile.objects.all()
    serializer_class = AdminAdvocateProfileSerializer


class AdminAdvocateEducationListView(AdminListBase):
    queryset = AdvocateEducation.objects.select_related('profile__user').all()
    serializer_class = AdminAdvocateEducationSerializer
    filterset_fields = ['profile']


class AdminAdvocateExperienceListView(AdminListBase):
    queryset = AdvocateExperience.objects.select_related('profile__user').all()
    serializer_class = AdminAdvocateExperienceSerializer
    filterset_fields = ['profile']


class AdminAdvocateAchievementListView(AdminListBase):
    queryset = AdvocateAchievement.objects.select_related('profile__user').all()
    serializer_class = AdminAdvocateAchievementSerializer
    filterset_fields = ['profile']


# ══════════════════════════════════════════════════════════════════════════════
# 6) CHANNELS
# ══════════════════════════════════════════════════════════════════════════════

class AdminChannelListView(AdminListBase):
    queryset = Channel.objects.all().order_by('-created_at')
    serializer_class = AdminChannelSerializer
    search_fields = ['name', 'city', 'state', 'court_name']
    filterset_fields = ['channel_type', 'is_official', 'is_private', 'city', 'state']
    ordering_fields = ['created_at', 'member_count']


class AdminChannelDetailView(AdminDetailBase):
    queryset = Channel.objects.all()
    serializer_class = AdminChannelSerializer


class AdminSubChannelListView(AdminListBase):
    queryset = SubChannel.objects.select_related('parent').all()
    serializer_class = AdminSubChannelSerializer
    search_fields = ['name']
    filterset_fields = ['parent', 'is_active', 'is_default']


class AdminChannelMembershipListView(AdminListBase):
    queryset = ChannelMembership.objects.select_related('channel', 'user').all()
    serializer_class = AdminChannelMembershipSerializer
    search_fields = ['user__username', 'channel__name']
    filterset_fields = ['channel', 'user', 'role', 'status']


class AdminChannelPostListView(AdminListBase):
    queryset = ChannelPost.objects.select_related('channel', 'author').all()
    serializer_class = AdminChannelPostSerializer
    search_fields = ['content', 'author__username', 'channel__name']
    filterset_fields = ['channel', 'sub_channel', 'is_pinned', 'is_announcement']
    ordering_fields = ['created_at', 'like_count', 'comment_count']


class AdminChannelPostDetailView(AdminDetailBase):
    """DELETE — inappropriate channel post ko turant hata sakte ho."""
    queryset = ChannelPost.objects.all()
    serializer_class = AdminChannelPostSerializer


class AdminChannelPostCommentListView(AdminListBase):
    queryset = ChannelPostComment.objects.select_related('post', 'author').all()
    serializer_class = AdminChannelPostCommentSerializer
    search_fields = ['content', 'author__username']
    filterset_fields = ['post']


class AdminChannelPostCommentDetailView(AdminDetailBase):
    queryset = ChannelPostComment.objects.all()
    serializer_class = AdminChannelPostCommentSerializer


# ══════════════════════════════════════════════════════════════════════════════
# 7) COMMUNITY FEED (Posts)
# ══════════════════════════════════════════════════════════════════════════════

class AdminHashtagListView(AdminListBase):
    queryset = Hashtag.objects.all()
    serializer_class = AdminHashtagSerializer
    search_fields = ['name']
    ordering_fields = ['post_count', 'created_at']


class AdminPostListView(AdminListBase):
    queryset = Post.objects.select_related('author').all().order_by('-created_at')
    serializer_class = AdminPostSerializer
    search_fields = ['content', 'author__username', 'author__full_name']
    filterset_fields = ['post_type', 'is_public', 'author']
    ordering_fields = ['created_at', 'like_count', 'comment_count', 'share_count']


class AdminPostDetailView(AdminDetailBase):
    """DELETE — spam/inappropriate feed post hatane ke liye."""
    queryset = Post.objects.all()
    serializer_class = AdminPostSerializer


class AdminPostCommentListView(AdminListBase):
    queryset = PostComment.objects.select_related('post', 'author').all()
    serializer_class = AdminPostCommentSerializer
    search_fields = ['content', 'author__username']
    filterset_fields = ['post']


class AdminPostCommentDetailView(AdminDetailBase):
    queryset = PostComment.objects.all()
    serializer_class = AdminPostCommentSerializer


# ══════════════════════════════════════════════════════════════════════════════
# 8) REPORTS & MODERATION
# ══════════════════════════════════════════════════════════════════════════════

class AdminReportListView(AdminListBase):
    """GET /api/admin/reports/?status=pending&report_type=post&reason=spam"""
    queryset = Report.objects.select_related('reporter', 'reviewed_by').all()
    serializer_class = AdminReportSerializer
    search_fields = ['description', 'reporter__username']
    filterset_fields = ['status', 'report_type', 'reason']
    ordering_fields = ['created_at']


class AdminReportDetailView(AdminDetailBase):
    queryset = Report.objects.all()
    serializer_class = AdminReportSerializer


class AdminReportResolveView(APIView):
    """POST /api/admin/reports/<uuid>/resolve/  Body: {"status": "resolved", "admin_notes": "..."}"""
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        report = _get404(Report, pk)
        report.status = request.data.get('status', 'resolved')
        report.admin_notes = request.data.get('admin_notes', '')
        report.reviewed_by = request.user
        report.save(update_fields=['status', 'admin_notes', 'reviewed_by', 'updated_at'])
        return Response({"message": "Report update ho gayi.", "status": report.status})


# ══════════════════════════════════════════════════════════════════════════════
# 9) NETWORKING (Connections / Follows)
# ══════════════════════════════════════════════════════════════════════════════

class AdminConnectionListView(AdminListBase):
    queryset = Connection.objects.select_related('sender', 'receiver').all()
    serializer_class = AdminConnectionSerializer
    search_fields = ['sender__username', 'receiver__username']
    filterset_fields = ['status']


class AdminFollowListView(AdminListBase):
    queryset = Follow.objects.select_related('follower', 'following').all()
    serializer_class = AdminFollowSerializer
    search_fields = ['follower__username', 'following__username']


# ══════════════════════════════════════════════════════════════════════════════
# 10) CHAT (rooms/messages — moderation-level visibility)
# ══════════════════════════════════════════════════════════════════════════════

class AdminChatRoomListView(AdminListBase):
    queryset = ChatRoom.objects.all().order_by('-updated_at')
    serializer_class = AdminChatRoomSerializer
    search_fields = ['name']
    filterset_fields = ['room_type']


class AdminChatRoomDetailView(AdminDetailBase):
    queryset = ChatRoom.objects.all()
    serializer_class = AdminChatRoomSerializer


class AdminMessageListView(AdminListBase):
    """GET /api/admin/messages/?room=<uuid> — kisi bhi room ki poori history dekho."""
    queryset = Message.objects.select_related('sender', 'room').all()
    serializer_class = AdminMessageSerializer
    search_fields = ['content', 'sender__username']
    filterset_fields = ['room', 'message_type', 'is_deleted']
    ordering_fields = ['created_at']


class AdminMessageDetailView(AdminDetailBase):
    """DELETE — abusive/illegal message force-delete karo."""
    queryset = Message.objects.all()
    serializer_class = AdminMessageSerializer


# ══════════════════════════════════════════════════════════════════════════════
# 11) CASE GROUPS
# ══════════════════════════════════════════════════════════════════════════════

class AdminCaseGroupListView(AdminListBase):
    queryset = CaseGroup.objects.select_related('created_by').all()
    serializer_class = AdminCaseGroupSerializer
    search_fields = ['name', 'case_number', 'court']
    filterset_fields = ['is_active', 'is_invite_only']


class AdminCaseGroupDetailView(AdminDetailBase):
    queryset = CaseGroup.objects.all()
    serializer_class = AdminCaseGroupSerializer


class AdminGroupMembershipListView(AdminListBase):
    queryset = GroupMembership.objects.select_related('group', 'user').all()
    serializer_class = AdminGroupMembershipSerializer
    filterset_fields = ['group', 'user', 'role']


class AdminGroupDocumentListView(AdminListBase):
    queryset = GroupDocument.objects.select_related('group', 'uploaded_by').all()
    serializer_class = AdminGroupDocumentSerializer
    filterset_fields = ['group']


# ══════════════════════════════════════════════════════════════════════════════
# 12) NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

class AdminNotificationListView(AdminListBase):
    queryset = Notification.objects.select_related('recipient', 'sender').all()
    serializer_class = AdminNotificationSerializer
    search_fields = ['title', 'body', 'recipient__username']
    filterset_fields = ['notif_type', 'is_read']


# ══════════════════════════════════════════════════════════════════════════════
# 13) HEARINGS & LEGAL UPDATES
# ══════════════════════════════════════════════════════════════════════════════

class AdminHearingListView(AdminListBase):
    queryset = Hearing.objects.select_related('advocate').all()
    serializer_class = AdminHearingSerializer
    search_fields = ['case_title', 'case_number', 'court', 'advocate__username']
    filterset_fields = ['hearing_type', 'is_completed']
    ordering_fields = ['hearing_date', 'hearing_time']


class AdminLegalUpdateListView(AdminListBase):
    queryset = LegalUpdate.objects.all().order_by('-created_at')
    serializer_class = AdminLegalUpdateSerializer
    search_fields = ['title', 'summary']
    filterset_fields = ['urgency', 'is_active']


class AdminLegalUpdateDetailView(AdminDetailBase):
    queryset = LegalUpdate.objects.all()
    serializer_class = AdminLegalUpdateSerializer


class AdminLegalUpdateCreateView(generics.CreateAPIView):
    """POST /api/admin/legal-updates/create/ — Home screen 'Recent Updates' ke liye."""
    permission_classes = [IsSuperUser]
    serializer_class = AdminLegalUpdateSerializer


# ══════════════════════════════════════════════════════════════════════════════
# 14) STORIES
# ══════════════════════════════════════════════════════════════════════════════

class AdminStoryListView(AdminListBase):
    queryset = Story.objects.select_related('author').all().order_by('-created_at')
    serializer_class = AdminStorySerializer
    search_fields = ['author__username', 'caption']
    filterset_fields = ['media_type']


class AdminStoryDetailView(AdminDetailBase):
    queryset = Story.objects.all()
    serializer_class = AdminStorySerializer


# ══════════════════════════════════════════════════════════════════════════════
# 15) OTP MONITORING (masked codes)
# ══════════════════════════════════════════════════════════════════════════════

class AdminOTPListView(AdminListBase):
    queryset = OTP.objects.select_related('user').all().order_by('-created_at')
    serializer_class = AdminOTPSerializer
    search_fields = ['user__username', 'user__email']
    filterset_fields = ['purpose', 'is_used']


# ══════════════════════════════════════════════════════════════════════════════
# small helper (avoids extra import clutter above)
# ══════════════════════════════════════════════════════════════════════════════

def _get404(model, pk):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(model, id=pk)