"""
Advocate App — Views (LegalConnect UI aligned)
New features added per screenshots:
- HomeDashboardView: stats + today's hearings + recent updates
- HearingView: CRUD for today's hearings
- LegalUpdateView: recent updates
- PinChatView: pin/unpin a chat room
- SubChannelView: sub-channels inside a channel
- HashtagListView & TrendingHashtagsView: trending topics
- SavePostView: save/unsave posts
- SharePostView: share count tracking
- UserPresenceView: Online/Away/Offline status update
- UserPreferencesView: theme, accent color, notifications, privacy settings
"""
import logging
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify

from rest_framework import generics, status, permissions, viewsets
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import (
    AdvocateProfile, AdvocateEducation, AdvocateExperience, AdvocateAchievement,
    Connection, Follow, OTP,
    ChatRoom, ChatParticipant, Message, MessageReadReceipt,
    Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment, ChannelPostLike,
    Post, PostReaction, PostComment, Hashtag, SavedPost, PostShare,
    CaseGroup, GroupMembership, GroupDocument,
    Notification, Report,
    Hearing, LegalUpdate,
)
from .serializers import (
    RegisterSerializer, LoginSerializer, OTPVerifySerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, ChangePasswordSerializer,
    UserProfileSerializer, AdminUserSerializer, AdminAdvocateVerifySerializer,
    AdvocateProfileSerializer, AdvocateVerificationSerializer,
    AdvocateEducationSerializer, AdvocateExperienceSerializer, AdvocateAchievementSerializer,
    ConnectionSerializer, ConnectionRequestSerializer, FollowSerializer,
    ChatRoomSerializer, MessageSerializer, CreateDirectChatSerializer, CreateGroupChatSerializer,
    ChannelSerializer, SubChannelSerializer, ChannelPostSerializer, ChannelPostCommentSerializer,
    PostSerializer, PostCommentSerializer, HashtagSerializer,
    CaseGroupSerializer, GroupDocumentSerializer,
    NotificationSerializer, ReportSerializer,
    HearingSerializer, LegalUpdateSerializer,
)
from .utils import (
    create_otp, verify_otp, send_otp_email,
    send_verification_status_email, send_connection_request_email,
    create_notification, get_direct_room, get_file_type,
)
from .filters import AdvocateProfileFilter, PostFilter, ChannelFilter
from project.permissions import IsOwnerOrReadOnly, IsMessageOwner

logger = logging.getLogger(__name__)
User = get_user_model()


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

class HealthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "status": "ok",
            "timestamp": timezone.now().isoformat(),
            "checks": {"database": "skipped", "api": "ok"},
            "message": "API is running",
            "version": "1.0.0",
        }, status=200)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH VIEWS  (login/register unchanged as requested)
# ══════════════════════════════════════════════════════════════════════════════

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if 'password2' not in data:
            data['password2'] = data.get('password', '')

        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
            print("🔴 Registration Validation Error:", serializer.errors)
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        user.is_verified = True
        user.save(update_fields=['is_verified'])

        # JWT tokens generate karo taaki Flutter seedha auto-login kar sake
        # OTP step hataya gaya — registration ke baad direct login
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)

        return Response({
            "message": "Account created successfully!",
            "user_id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_verified": True,
            # Tokens — Flutter in se auto-login karega
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "onboarding_complete": False,   # Naya user — onboarding pending
        }, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            username = request.data.get('username', '').lower()
            try:
                user = User.objects.get(username=username)
                # onboarding_complete — AdvocateProfile se safe fetch
                onboarding_complete = False
                try:
                    onboarding_complete = user.advocate_profile.onboarding_complete
                except Exception:
                    onboarding_complete = False

                response.data['user'] = {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email or '',
                    'full_name': user.full_name,
                    'is_verified': user.is_verified,
                    'is_advocate': user.is_advocate,
                    'advocate_status': user.advocate_status,
                    'is_online': user.is_online,
                    'presence_status': user.presence_status,
                    'theme': user.theme,
                    'accent_color': user.accent_color,
                    'onboarding_complete': onboarding_complete,  # ← Flutter routing ke liye
                }
            except User.DoesNotExist:
                pass
        return response


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh_token"))
            token.blacklist()
        except Exception:
            pass
        User.objects.filter(id=request.user.id).update(
            is_online=False,
            presence_status='offline',
            last_seen=timezone.now()
        )
        return Response({"message": "Logged out successfully."})


class VerifyOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(email=serializer.validated_data['email'])
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)
        ok, error = verify_otp(user, serializer.validated_data['code'], serializer.validated_data['purpose'])
        if not ok:
            return Response({"error": error}, status=400)
        if serializer.validated_data['purpose'] == 'email_verify':
            user.is_verified = True
            user.save(update_fields=['is_verified'])
        return Response({"message": "OTP verified successfully."})


class ResendOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email   = request.data.get('email')
        purpose = request.data.get('purpose', 'email_verify')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)
        otp = create_otp(user, purpose)
        send_otp_email(user, otp.code, purpose)
        return Response({"message": f"OTP sent to {email}."})


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '')
        try:
            user = User.objects.get(email=email)
            otp  = create_otp(user, 'forgot_password')
            try:
                send_otp_email(user, otp.code, 'forgot_password')
            except Exception:
                pass
        except User.DoesNotExist:
            pass
        return Response({"message": "If this email is registered, you will receive an OTP."})


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email        = request.data.get('email', '')
        code         = request.data.get('code', '')
        new_password = request.data.get('new_password', '')
        if not all([email, code, new_password]):
            return Response({"error": "email, code and new_password are required."}, status=400)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)
        ok, error = verify_otp(user, code, 'forgot_password')
        if not ok:
            return Response({"error": error}, status=400)
        user.set_password(new_password)
        user.save(update_fields=['password'])
        return Response({"message": "Password reset successfully."})


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')
        if not request.user.check_password(old_password):
            return Response({"error": "Current password is incorrect."}, status=400)
        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        return Response({"message": "Password changed successfully."})


class DeleteAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        password = request.data.get('password', '')
        if not request.user.check_password(password):
            return Response({"error": "Password is incorrect."}, status=400)
        request.user.is_active = False
        request.user.save(update_fields=['is_active'])
        return Response({"message": "Account deleted."})


# ══════════════════════════════════════════════════════════════════════════════
# USER VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class MyProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/users/me/"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserDetailView(generics.RetrieveAPIView):
    """GET /api/users/<id>/"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = User.objects.filter(is_active=True)


class UserPresenceView(APIView):
    """
    PATCH /api/users/me/presence/
    Profile screen: Online/Away/Offline status toggle.
    Body: { "presence_status": "online" | "away" | "offline" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        presence = request.data.get('presence_status', '')
        if presence not in ('online', 'away', 'offline'):
            return Response({"error": "Invalid presence_status. Use: online, away, offline."}, status=400)

        is_online = presence == 'online'
        last_seen = timezone.now() if not is_online else None

        User.objects.filter(id=request.user.id).update(
            presence_status=presence,
            is_online=is_online,
            last_seen=last_seen,
        )
        return Response({"presence_status": presence, "is_online": is_online})


class UserPreferencesView(APIView):
    """
    PATCH /api/users/me/preferences/
    Profile screen: theme, accent_color, notification toggles, privacy settings.
    Body: any combination of preference fields.
    """
    permission_classes = [permissions.IsAuthenticated]

    ALLOWED_FIELDS = [
        'theme', 'accent_color',
        'notif_messages', 'notif_group_mentions', 'notif_stories', 'notif_calls',
        'privacy_read_receipts', 'privacy_last_seen', 'privacy_online_status',
    ]

    def patch(self, request):
        user = request.user
        updated = {}
        for field in self.ALLOWED_FIELDS:
            if field in request.data:
                setattr(user, field, request.data[field])
                updated[field] = request.data[field]

        if not updated:
            return Response({"error": "No valid preference fields provided."}, status=400)

        user.save(update_fields=list(updated.keys()))
        return Response({"message": "Preferences updated.", "updated": updated})


# ══════════════════════════════════════════════════════════════════════════════
# HOME SCREEN — Dashboard, Hearings, Legal Updates
# ══════════════════════════════════════════════════════════════════════════════

class HomeDashboardView(APIView):
    """
    GET /api/home/dashboard/
    Home screen: stats cards + today's hearings + recent updates.
    Returns:
      - cases_handled, connections, hearings_today, advocate_rating
      - todays_hearings (list)
      - recent_updates (list)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now().date()

        # Stats
        try:
            profile = user.advocate_profile
            connection_count = profile.connection_count
        except AdvocateProfile.DoesNotExist:
            connection_count = 0

        todays_hearings = Hearing.objects.filter(
            advocate=user, hearing_date=today
        ).order_by('hearing_time')

        recent_updates = LegalUpdate.objects.filter(is_active=True)[:5]

        return Response({
            "cases_handled": user.cases_handled,
            "connections": connection_count,
            "hearings_today": todays_hearings.count(),
            "advocate_rating": float(user.advocate_rating),
            "todays_hearings": HearingSerializer(todays_hearings, many=True).data,
            "recent_updates": LegalUpdateSerializer(recent_updates, many=True).data,
        })


class HearingListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/hearings/          — list user's hearings (filter: ?date=YYYY-MM-DD)
    POST /api/hearings/          — create a hearing
    Home screen: Today's Hearings section
    """
    serializer_class = HearingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Hearing.objects.filter(advocate=self.request.user)
        date = self.request.query_params.get('date')
        if date:
            qs = qs.filter(hearing_date=date)
        today_only = self.request.query_params.get('today')
        if today_only:
            qs = qs.filter(hearing_date=timezone.now().date())
        return qs.order_by('hearing_date', 'hearing_time')

    def perform_create(self, serializer):
        serializer.save(advocate=self.request.user)


class HearingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/hearings/<id>/"""
    serializer_class = HearingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Hearing, id=self.kwargs['pk'], advocate=self.request.user)


class LegalUpdateListView(generics.ListAPIView):
    """
    GET /api/legal-updates/
    Home screen: Recent Updates section.
    Admin can create via admin panel.
    """
    serializer_class = LegalUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LegalUpdate.objects.filter(is_active=True)


# ══════════════════════════════════════════════════════════════════════════════
# ADVOCATE PROFILE VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class AdvocateProfileListView(generics.ListAPIView):
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = AdvocateProfileFilter
    search_fields = ['user__full_name', 'bio', 'city', 'state']
    ordering_fields = ['years_of_experience', 'connection_count', 'follower_count']
    ordering = ['-connection_count']

    def get_queryset(self):
        # advocate_status='approved' filter hataya — naye registered users bhi
        # search mein dikhne chahiye, sirf active aur public profiles
        return AdvocateProfile.objects.filter(
            user__is_active=True,
            is_public=True,
        ).select_related('user').prefetch_related('education', 'experience', 'achievements')


class MyAdvocateProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return profile


class AdvocateOnboardingView(APIView):
    """
    POST/PATCH /api/advocates/me/onboarding/

    Pehli baar login ke baad advocate apna basic profile fill karta hai.
    Ek hi request mein User.bio + AdvocateProfile fields + onboarding_complete = True set hota hai.

    Expected payload:
    {
        "primary_court": "district_court",
        "practice_areas": ["criminal", "civil"],
        "experience_years": 5,
        "cases_handled": 120,
        "bar_enrollment_no": "MAH/1234/2019",
        "bio": "Experienced criminal lawyer..."
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return self._handle(request)

    def patch(self, request):
        return self._handle(request)

    def _handle(self, request):
        user = request.user
        data = request.data

        # 1. Bio update — User model pe
        bio = data.get('bio', '').strip()
        if bio:
            # bio User model mein nahi hai — AdvocateProfile mein store karo
            pass  # neeche profile pe set hoga

        # 2. AdvocateProfile update
        profile, _ = AdvocateProfile.objects.get_or_create(user=user)

        if data.get('primary_court'):
            profile.primary_court = data['primary_court']

        if data.get('practice_areas') is not None:
            areas = data.get('practice_areas')
            if isinstance(areas, str):
                import json
                try:
                    areas = json.loads(areas)
                except (ValueError, TypeError):
                    areas = [areas]
            profile.specializations = areas

        if data.get('experience_years') is not None:
            profile.years_of_experience = int(data['experience_years'])

        if data.get('bar_enrollment_no'):
            profile.enrollment_number = data['bar_enrollment_no']

        if bio:
            profile.bio = bio

        # City + State — onboarding step 5
        if data.get('city'):
            profile.city = data['city'].strip()
        if data.get('state'):
            profile.state = data['state'].strip()

        # Profile photo URL — Cloudinary se direct upload, backend ko URL milta hai
        if data.get('profile_photo_url'):
            profile.profile_photo = data['profile_photo_url']

        profile.onboarding_complete = True
        update_fields = [
            'primary_court', 'specializations', 'years_of_experience',
            'enrollment_number', 'bio', 'onboarding_complete',
            'city', 'state', 'profile_photo',
        ]
        profile.save(update_fields=update_fields)

        # 3. cases_handled — User model pe hai
        if data.get('cases_handled') is not None:
            user.cases_handled = int(data['cases_handled'])
            user.save(update_fields=['cases_handled'])

        return Response({
            'message': 'Onboarding complete!',
            'onboarding_complete': True,
        }, status=status.HTTP_200_OK)


class AdvocateProfileDetailView(generics.RetrieveAPIView):
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = get_object_or_404(User, id=self.kwargs['user_id'], is_active=True)
        profile, _ = AdvocateProfile.objects.get_or_create(user=user)
        return profile


class AdvocateVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        profile, _ = AdvocateProfile.objects.get_or_create(user=request.user)
        bar_council_id = request.data.get('bar_council_id', '')
        document       = request.FILES.get('document') or request.FILES.get('bar_council_id_image')
        if bar_council_id:
            profile.bar_council_id = bar_council_id
        if document:
            profile.bar_council_id_image = document
        profile.save()
        request.user.is_advocate      = True
        request.user.advocate_status  = 'pending'
        request.user.save(update_fields=['is_advocate', 'advocate_status'])
        return Response({
            "message": "Verification submitted. Admin will review within 24-48 hours.",
            "status": "pending",
        })


class AdvocateEducationViewSet(viewsets.ModelViewSet):
    serializer_class   = AdvocateEducationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateEducation.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


class AdvocateExperienceViewSet(viewsets.ModelViewSet):
    serializer_class   = AdvocateExperienceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateExperience.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


class AdvocateAchievementViewSet(viewsets.ModelViewSet):
    serializer_class   = AdvocateAchievementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateAchievement.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTIONS
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionListView(generics.ListAPIView):
    serializer_class   = ConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Connection.objects.filter(
            Q(sender=self.request.user) | Q(receiver=self.request.user),
            status='accepted'
        ).select_related('sender', 'receiver')


class PendingConnectionsView(generics.ListAPIView):
    serializer_class   = ConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Connection.objects.filter(
            receiver=self.request.user, status='pending'
        ).select_related('sender')


class SendConnectionRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ConnectionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receiver_id = serializer.validated_data['receiver_id']
        receiver = get_object_or_404(User, id=receiver_id, is_active=True)

        if receiver == request.user:
            return Response({"error": "Cannot send request to yourself."}, status=400)

        # Check if a pending/accepted connection already exists in either direction
        existing = Connection.objects.filter(
            sender__in=[request.user, receiver],
            receiver__in=[request.user, receiver],
        ).first()
        if existing:
            if existing.status == 'accepted':
                return Response({"error": "Already connected."}, status=400)
            return Response({"error": "Connection request already sent."}, status=400)

        conn = Connection.objects.create(
            sender=request.user,
            receiver=receiver,
            message=serializer.validated_data.get('message', ''),
        )
        send_connection_request_email(request.user, receiver)
        create_notification(
            recipient=receiver, notif_type='connection_request',
            title='New Connection Request',
            body=f"{request.user.full_name} sent you a connection request.",
            sender=request.user,
        )
        return Response(ConnectionSerializer(conn, context={'request': request}).data, status=201)


class ConnectionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        new_status = request.data.get('status', '')
        connection = get_object_or_404(Connection, id=pk)
        if new_status in ('accepted', 'rejected') and connection.receiver != request.user:
            return Response({"error": "Only the receiver can accept/reject."}, status=403)
        connection.status = new_status
        connection.save(update_fields=['status', 'updated_at'])
        if new_status == 'accepted':
            self._bump_connection_counts(connection)
            create_notification(
                recipient=connection.sender,
                notif_type='connection_accepted',
                title='Connection Accepted!',
                body=f"{request.user.full_name} accepted your connection request.",
                sender=request.user,
            )
        return Response(ConnectionSerializer(connection, context={'request': request}).data)

    def delete(self, request, pk):
        connection = get_object_or_404(
            Connection,
            Q(sender=request.user) | Q(receiver=request.user),
            id=pk,
        )
        if connection.status == 'accepted':
            self._decrement_connection_counts(connection)
        connection.delete()
        return Response(status=204)

    def _bump_connection_counts(self, conn):
        for user in [conn.sender, conn.receiver]:
            try:
                p = user.advocate_profile
                p.connection_count += 1
                p.save(update_fields=['connection_count'])
            except AdvocateProfile.DoesNotExist:
                pass

    def _decrement_connection_counts(self, conn):
        for user in [conn.sender, conn.receiver]:
            try:
                p = user.advocate_profile
                p.connection_count = max(0, p.connection_count - 1)
                p.save(update_fields=['connection_count'])
            except AdvocateProfile.DoesNotExist:
                pass


class FollowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = get_object_or_404(User, id=user_id, is_active=True)
        if target == request.user:
            return Response({"error": "Cannot follow yourself."}, status=400)

        follow, created = Follow.objects.get_or_create(
            follower=request.user, following=target
        )
        if not created:
            # Already following — unfollow (toggle)
            follow.delete()
            try:
                p = target.advocate_profile
                p.follower_count = max(0, p.follower_count - 1)
                p.save(update_fields=['follower_count'])
            except AdvocateProfile.DoesNotExist:
                pass
            return Response({"is_following": False, "message": f"Unfollowed {target.full_name}."})

        # Newly followed
        try:
            target.advocate_profile.follower_count += 1
            target.advocate_profile.save(update_fields=['follower_count'])
        except AdvocateProfile.DoesNotExist:
            pass
        create_notification(
            recipient=target, notif_type='follow',
            title='New Follower',
            body=f"{request.user.full_name} started following you.",
            sender=request.user,
        )
        return Response({"is_following": True, "message": f"Now following {target.full_name}."}, status=201)

    def delete(self, request, user_id):
        target = get_object_or_404(User, id=user_id)
        Follow.objects.filter(follower=request.user, following=target).delete()
        try:
            p = target.advocate_profile
            p.follower_count = max(0, p.follower_count - 1)
            p.save(update_fields=['follower_count'])
        except AdvocateProfile.DoesNotExist:
            pass
        return Response(status=204)


class SuggestedAdvocatesView(generics.ListAPIView):
    """
    GET /api/network/suggested/
    Feed screen: People to Follow sidebar.
    """
    serializer_class   = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        connected = Connection.objects.filter(
            Q(sender=self.request.user) | Q(receiver=self.request.user)
        ).values_list('sender_id', 'receiver_id')
        excluded = set()
        for s, r in connected:
            excluded.add(s); excluded.add(r)
        excluded.add(self.request.user.id)

        return AdvocateProfile.objects.filter(
            user__is_active=True, user__advocate_status='approved',
        ).exclude(user__id__in=excluded).order_by('?')[:20]


# ══════════════════════════════════════════════════════════════════════════════
# CHAT / MESSAGING
# Chat screen: All/Direct/Groups/Pinned tabs, pin/unpin chat
# ══════════════════════════════════════════════════════════════════════════════

class ChatRoomListView(generics.ListAPIView):
    """
    GET /api/chat/rooms/
    Supports ?tab=direct|group|pinned to filter tabs.
    """
    serializer_class   = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tab = self.request.query_params.get('tab', 'all')
        qs = ChatRoom.objects.filter(
            room_participants__user=self.request.user
        ).prefetch_related('room_participants__user', 'messages').distinct()

        if tab == 'direct':
            qs = qs.filter(room_type='direct')
        elif tab == 'group':
            qs = qs.filter(room_type='group')
        elif tab == 'pinned':
            # Only rooms pinned by current user
            qs = qs.filter(room_participants__user=self.request.user,
                           room_participants__is_pinned=True)

        return qs.order_by('-updated_at')


class PinChatView(APIView):
    """
    POST   /api/chat/rooms/<room_id>/pin/    — pin a chat (Pinned tab)
    DELETE /api/chat/rooms/<room_id>/pin/    — unpin a chat
    Chat screen: Pinned tab
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        participant = get_object_or_404(
            ChatParticipant, room_id=room_id, user=request.user
        )
        participant.is_pinned = True
        participant.save(update_fields=['is_pinned'])
        return Response({"message": "Chat pinned.", "is_pinned": True})

    def delete(self, request, room_id):
        participant = get_object_or_404(
            ChatParticipant, room_id=room_id, user=request.user
        )
        participant.is_pinned = False
        participant.save(update_fields=['is_pinned'])
        return Response({"message": "Chat unpinned.", "is_pinned": False})


class CreateDirectChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateDirectChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        other = get_object_or_404(User, id=serializer.validated_data['user_id'], is_active=True)
        room, created = get_direct_room(request.user, other)
        return Response(
            ChatRoomSerializer(room, context={'request': request}).data,
            status=201 if created else 200,
        )


class CreateGroupChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateGroupChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        room = ChatRoom.objects.create(
            room_type='group',
            name=data['name'],
            description=data.get('description', ''),
            created_by=request.user,
        )
        ChatParticipant.objects.create(room=room, user=request.user, role='admin')
        users = User.objects.filter(id__in=data['participant_ids'], is_active=True)
        for u in users:
            if u != request.user:
                ChatParticipant.objects.create(room=room, user=u)
        return Response(ChatRoomSerializer(room, context={'request': request}).data, status=201)


class MessageListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id, room_participants__user=request.user)
        page = int(request.query_params.get('page', 1))
        page_size = 50
        messages = Message.objects.filter(room=room).select_related('sender').order_by('created_at')
        total = messages.count()
        start = (page - 1) * page_size
        messages = messages[start: start + page_size]
        ChatParticipant.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        return Response({
            "count": total,
            "results": MessageSerializer(messages, many=True, context={'request': request}).data,
        })

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id, room_participants__user=request.user)
        file         = request.FILES.get('file')
        content      = request.data.get('content', '')
        msg_type     = request.data.get('message_type', 'text' if not file else get_file_type(file))
        reply_to_id  = request.data.get('reply_to')
        reply_to     = Message.objects.filter(id=reply_to_id, room=room).first() if reply_to_id else None
        msg = Message.objects.create(
            room=room, sender=request.user,
            message_type=msg_type, content=content,
            file=file,
            file_name=file.name if file else '',
            file_size=file.size if file else None,
            reply_to=reply_to,
        )
        room.updated_at = timezone.now()
        room.save(update_fields=['updated_at'])
        return Response(MessageSerializer(msg, context={'request': request}).data, status=201)


class MessageDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        msg = get_object_or_404(Message, id=pk, sender=request.user, is_deleted=False)
        content = request.data.get('content', '').strip()
        if not content:
            return Response({"error": "content is required."}, status=400)
        msg.content   = content
        msg.is_edited = True
        msg.save(update_fields=['content', 'is_edited', 'updated_at'])
        return Response(MessageSerializer(msg, context={'request': request}).data)

    def delete(self, request, pk):
        msg = get_object_or_404(Message, id=pk, sender=request.user)
        msg.is_deleted  = True
        msg.content     = "This message was deleted."
        msg.deleted_at  = timezone.now()
        msg.save(update_fields=['is_deleted', 'content', 'deleted_at'])
        return Response(status=204)


class MarkMessagesReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id, room_participants__user=request.user)
        for msg in Message.objects.filter(room=room, is_deleted=False).exclude(sender=request.user):
            MessageReadReceipt.objects.get_or_create(message=msg, user=request.user)
        ChatParticipant.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        return Response({"message": "Messages marked as read."})


# ══════════════════════════════════════════════════════════════════════════════
# CHANNELS
# Channel screen: list with sub-channels, pinned banner, sub-channel posts
# ══════════════════════════════════════════════════════════════════════════════

class ChannelListView(generics.ListAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class    = ChannelFilter
    search_fields      = ['name', 'description', 'court_name', 'city', 'state']
    ordering_fields    = ['member_count', 'created_at']
    ordering           = ['-member_count']

    def get_queryset(self):
        return Channel.objects.filter(is_private=False).prefetch_related('sub_channels')


class MyChannelsView(generics.ListAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Channel.objects.filter(memberships__user=self.request.user).prefetch_related('sub_channels')


class ChannelDetailView(generics.RetrieveAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset           = Channel.objects.prefetch_related('sub_channels')
    lookup_field       = 'id'


class CreateChannelView(generics.CreateAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        name = serializer.validated_data.get('name', '')
        slug = slugify(name)
        base_slug, counter = slug, 1
        while Channel.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"; counter += 1
        channel = serializer.save(created_by=self.request.user, slug=slug)
        ChannelMembership.objects.create(channel=channel, user=self.request.user, role='admin')
        channel.member_count = 1
        channel.save(update_fields=['member_count'])


class JoinChannelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        _, created = ChannelMembership.objects.get_or_create(channel=channel, user=request.user)
        if not created:
            return Response({"error": "Already a member."}, status=400)
        channel.member_count += 1
        channel.save(update_fields=['member_count'])
        return Response({"message": f"Joined {channel.name}."}, status=201)


class LeaveChannelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        deleted, _ = ChannelMembership.objects.filter(channel=channel, user=request.user).delete()
        if deleted:
            channel.member_count = max(0, channel.member_count - 1)
            channel.save(update_fields=['member_count'])
        return Response(status=204)


class SubChannelListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/channels/<channel_id>/sub-channels/   — list sub-channels
    POST /api/channels/<channel_id>/sub-channels/   — create sub-channel (admin only)
    Channel screen: sub-channel list (Daily Cause List, Latest Judgments, etc.)
    """
    serializer_class   = SubChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        channel = get_object_or_404(Channel, id=self.kwargs['channel_id'])
        return SubChannel.objects.filter(parent=channel, is_active=True)

    def perform_create(self, serializer):
        channel = get_object_or_404(Channel, id=self.kwargs['channel_id'])
        # Only channel admin can create sub-channels
        membership = ChannelMembership.objects.filter(
            channel=channel, user=self.request.user, role='admin'
        ).first()
        if not membership:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only channel admins can create sub-channels.")
        name = serializer.validated_data.get('name', '')
        slug = slugify(name)
        base_slug, counter = slug, 1
        while SubChannel.objects.filter(parent=channel, slug=slug).exists():
            slug = f"{base_slug}-{counter}"; counter += 1
        serializer.save(parent=channel, slug=slug)


class ChannelPostListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/channels/<channel_id>/posts/
    POST /api/channels/<channel_id>/posts/
    Supports ?sub_channel=<id> to filter by sub-channel.
    """
    serializer_class   = ChannelPostSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        channel = get_object_or_404(Channel, id=self.kwargs['channel_id'])
        qs = ChannelPost.objects.filter(channel=channel).select_related('author')
        sub_channel_id = self.request.query_params.get('sub_channel')
        if sub_channel_id:
            qs = qs.filter(sub_channel_id=sub_channel_id)
        return qs

    def perform_create(self, serializer):
        channel = get_object_or_404(
            Channel, id=self.kwargs['channel_id'],
            memberships__user=self.request.user,
        )
        attachment = self.request.FILES.get('attachment')
        att_type   = get_file_type(attachment) if attachment else ''
        sub_channel_id = self.request.data.get('sub_channel')
        sub_channel = None
        if sub_channel_id:
            sub_channel = SubChannel.objects.filter(id=sub_channel_id, parent=channel).first()
        serializer.save(
            author=self.request.user, channel=channel,
            attachment=attachment, attachment_type=att_type,
            sub_channel=sub_channel,
        )


class ChannelPostLikeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(ChannelPost, id=pk)
        like, created = ChannelPostLike.objects.get_or_create(post=post, user=request.user)
        if not created:
            like.delete()
            post.like_count = max(0, post.like_count - 1)
            post.save(update_fields=['like_count'])
            return Response({"liked": False, "like_count": post.like_count})
        post.like_count += 1
        post.save(update_fields=['like_count'])
        return Response({"liked": True, "like_count": post.like_count})


class ChannelPostCommentView(generics.ListCreateAPIView):
    serializer_class   = ChannelPostCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChannelPostComment.objects.filter(
            post_id=self.kwargs['post_id'], parent=None,
        ).select_related('author')

    def perform_create(self, serializer):
        post = get_object_or_404(ChannelPost, id=self.kwargs['post_id'])
        serializer.save(author=self.request.user, post=post)
        post.comment_count += 1
        post.save(update_fields=['comment_count'])


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY FEED
# Feed screen: hashtags, trending, save/share, post types
# ══════════════════════════════════════════════════════════════════════════════

class TrendingHashtagsView(generics.ListAPIView):
    """
    GET /api/feed/trending/
    Feed screen: Trending Now section (top 10 hashtags by post count).
    """
    serializer_class   = HashtagSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Hashtag.objects.order_by('-post_count')[:10]


class FeedListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/feed/   — home feed
    POST /api/feed/   — create post (content, post_type, media, is_public, hashtag_names)
    """
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class    = PostFilter
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        connected = Connection.objects.filter(
            Q(sender=self.request.user) | Q(receiver=self.request.user),
            status='accepted',
        ).values_list('sender_id', 'receiver_id')

        ids = set()

        for s, r in connected:
            ids.add(s)
            ids.add(r)

        ids.add(self.request.user.id)

        # Hashtag filter
        hashtag = self.request.query_params.get('hashtag')

        qs = Post.objects.filter(
            Q(author_id__in=ids) | Q(is_public=True)
        ).select_related('author').distinct().order_by('-created_at')

        if hashtag:
            qs = qs.filter(
                hashtags__name__iexact=hashtag.lstrip('#')
            )

        return qs

    def perform_create(self, serializer):

        file = self.request.FILES.get('media')
        media_type = get_file_type(file) if file else ''

        post = serializer.save(
            author=self.request.user,
            media=file,
            media_type=media_type
        )

        # -------------------------
        # Handle hashtags safely
        # -------------------------
        data = self.request.data

        if hasattr(data, 'getlist'):
            hashtag_names = data.getlist('hashtag_names[]')
        else:
            hashtag_names = data.get('hashtag_names', [])

        # fallback from serializer
        if not hashtag_names:
            hashtag_names = serializer.validated_data.get(
                'hashtag_names',
                []
            )

        # convert string -> list
        if isinstance(hashtag_names, str):
            hashtag_names = [hashtag_names]

        # Attach hashtags
        for name in hashtag_names:

            if not isinstance(name, str):
                continue

            name = name.strip().lstrip('#').lower()

            if name:
                tag, created = Hashtag.objects.get_or_create(name=name)

                post.hashtags.add(tag)

                tag.post_count += 1
                tag.save(update_fields=['post_count'])

        # -------------------------
        # Update author post count
        # -------------------------
        try:
            profile = post.author.advocate_profile
            profile.post_count += 1
            profile.save(update_fields=['post_count'])

        except AdvocateProfile.DoesNotExist:
            pass


class PostDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        return Response(PostSerializer(post, context={'request': request}).data)

    def delete(self, request, pk):
        post = get_object_or_404(Post, id=pk, author=request.user)
        post.delete()
        # Decrement cached post_count
        try:
            profile = request.user.advocate_profile
            profile.post_count = max(0, profile.post_count - 1)
            profile.save(update_fields=['post_count'])
        except AdvocateProfile.DoesNotExist:
            pass
        return Response(status=204)


class PostReactView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        post          = get_object_or_404(Post, id=pk)
        reaction_type = request.data.get('reaction_type', 'like')
        existing = PostReaction.objects.filter(post=post, user=request.user).first()
        if existing:
            if existing.reaction_type == reaction_type:
                existing.delete()
                post.like_count = max(0, post.like_count - 1)
                post.save(update_fields=['like_count'])
                return Response({"reacted": False, "like_count": post.like_count})
            existing.reaction_type = reaction_type
            existing.save()
            return Response({"reacted": True, "type": reaction_type, "like_count": post.like_count})
        PostReaction.objects.create(post=post, user=request.user, reaction_type=reaction_type)
        post.like_count += 1
        post.save(update_fields=['like_count'])
        return Response({"reacted": True, "type": reaction_type, "like_count": post.like_count})

    def delete(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        deleted, _ = PostReaction.objects.filter(post=post, user=request.user).delete()
        if deleted:
            post.like_count = max(0, post.like_count - 1)
            post.save(update_fields=['like_count'])
        return Response(status=204)


class PostCommentView(generics.ListCreateAPIView):
    serializer_class   = PostCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PostComment.objects.filter(
            post_id=self.kwargs['post_id'], parent=None,
        ).select_related('author').order_by('created_at')

    def perform_create(self, serializer):
        post = get_object_or_404(Post, id=self.kwargs['post_id'])
        serializer.save(author=self.request.user, post=post)
        post.comment_count += 1
        post.save(update_fields=['comment_count'])
        if post.author != self.request.user:
            create_notification(
                recipient=post.author, notif_type='comment',
                title='New Comment',
                body=f"{self.request.user.full_name} commented on your post.",
                sender=self.request.user,
                data={'post_id': str(post.id)},
            )


class SavePostView(APIView):
    """
    POST   /api/feed/<pk>/save/   — save a post (Feed: Save button)
    DELETE /api/feed/<pk>/save/   — unsave a post
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        _, created = SavedPost.objects.get_or_create(user=request.user, post=post)
        if not created:
            return Response({"error": "Post already saved."}, status=400)
        return Response({"saved": True, "message": "Post saved."}, status=201)

    def delete(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        SavedPost.objects.filter(user=request.user, post=post).delete()
        return Response({"saved": False, "message": "Post unsaved."})


class SavedPostListView(generics.ListAPIView):
    """
    GET /api/feed/saved/   — list user's saved posts
    """
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        saved_ids = SavedPost.objects.filter(user=self.request.user).values_list('post_id', flat=True)
        return Post.objects.filter(id__in=saved_ids).select_related('author').order_by('-created_at')


class SharePostView(APIView):
    """
    POST /api/feed/<pk>/share/   — record a share (Feed: Share button)
    Increments share_count on the post.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        PostShare.objects.create(user=request.user, post=post)
        post.share_count += 1
        post.save(update_fields=['share_count'])
        return Response({"shared": True, "share_count": post.share_count})


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

class NotificationListView(generics.ListAPIView):
    serializer_class   = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related('sender').order_by('-created_at')


class UnreadNotificationCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread_count": count})


class MarkNotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        notif = get_object_or_404(Notification, id=pk, recipient=request.user)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response({"message": "Marked as read."})


class MarkAllNotificationsReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({"message": "All notifications marked as read."})


# ══════════════════════════════════════════════════════════════════════════════
# CASE GROUPS
# ══════════════════════════════════════════════════════════════════════════════

class CaseGroupListCreateView(generics.ListCreateAPIView):
    serializer_class   = CaseGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CaseGroup.objects.filter(memberships__user=self.request.user, is_active=True)

    def perform_create(self, serializer):
        group = serializer.save(created_by=self.request.user)
        GroupMembership.objects.create(group=group, user=self.request.user, role='admin')


class CaseGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = CaseGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(CaseGroup, id=self.kwargs['pk'], memberships__user=self.request.user)


class InviteToCaseGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        group = get_object_or_404(CaseGroup, id=pk)
        if not group.memberships.filter(user=request.user, role='admin').exists():
            return Response({"error": "Only admins can invite."}, status=403)
        added = []
        for uid in request.data.get('user_ids', []):
            user = User.objects.filter(id=uid, is_active=True).first()
            if user:
                _, created = GroupMembership.objects.get_or_create(group=group, user=user)
                if created:
                    added.append(str(user.id))
                    create_notification(
                        recipient=user, notif_type='system',
                        title='Case Group Invitation',
                        body=f"{request.user.full_name} added you to: {group.name}",
                        sender=request.user, data={'group_id': str(group.id)},
                    )
        return Response({"added": added, "message": f"{len(added)} user(s) added."})


class GroupDocumentView(generics.ListCreateAPIView):
    serializer_class   = GroupDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def get_queryset(self):
        group = get_object_or_404(CaseGroup, id=self.kwargs['group_id'], memberships__user=self.request.user)
        return GroupDocument.objects.filter(group=group)

    def perform_create(self, serializer):
        group = get_object_or_404(CaseGroup, id=self.kwargs['group_id'], memberships__user=self.request.user)
        file  = self.request.FILES.get('file')
        serializer.save(group=group, uploaded_by=self.request.user,
                        file_name=file.name if file else '',
                        file_size=file.size if file else 0)


# ══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════════════

class ReportCreateView(generics.CreateAPIView):
    serializer_class   = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class AdminUserListView(generics.ListAPIView):
    serializer_class   = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]
    search_fields      = ['email', 'full_name', 'username']
    ordering           = ['-date_joined']

    def get_queryset(self):
        qs = User.objects.all()
        s  = self.request.query_params.get('advocate_status')
        if s: qs = qs.filter(advocate_status=s)
        return qs


class AdminUserDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset           = User.objects.all()


class AdminBanUserView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        user = get_object_or_404(User, id=pk)
        user.is_active = False; user.save(update_fields=['is_active'])
        return Response({"message": f"{user.username} banned."})


class AdminUnbanUserView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        user = get_object_or_404(User, id=pk)
        user.is_active = True; user.save(update_fields=['is_active'])
        return Response({"message": f"{user.username} unbanned."})


class AdminPendingVerificationsView(generics.ListAPIView):
    serializer_class   = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return User.objects.filter(advocate_status='pending').select_related('advocate_profile')


class AdminVerifyAdvocateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, user_id):
        user       = get_object_or_404(User, id=user_id, advocate_status='pending')
        serializer = AdminAdvocateVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']
        notes      = serializer.validated_data.get('admin_notes', '')
        user.advocate_status = new_status
        user.save(update_fields=['advocate_status'])
        send_verification_status_email(user, new_status, notes)
        notif_type = 'verification_approved' if new_status == 'approved' else 'verification_rejected'
        title      = '✅ Verification Approved!' if new_status == 'approved' else 'Verification Update'
        body       = "Your advocate profile is verified!" if new_status == 'approved' else f"Not approved: {notes}"
        create_notification(recipient=user, notif_type=notif_type, title=title, body=body)
        return Response({"message": f"Advocate {new_status}.", "user_id": str(user.id), "status": new_status})


class AdminReportListView(generics.ListAPIView):
    serializer_class   = ReportSerializer
    permission_classes = [permissions.IsAdminUser]
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = Report.objects.all().select_related('reporter')
        s  = self.request.query_params.get('status', 'pending')
        if s: qs = qs.filter(status=s)
        return qs


class AdminReportResolveView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        report = get_object_or_404(Report, id=pk)
        report.status      = request.data.get('status', 'resolved')
        report.admin_notes = request.data.get('admin_notes', '')
        report.reviewed_by = request.user
        report.save(update_fields=['status', 'admin_notes', 'reviewed_by', 'updated_at'])
        return Response({"message": "Report updated.", "status": report.status})


class AdminAnalyticsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from datetime import timedelta
        last30 = timezone.now() - timedelta(days=30)
        return Response({
            "total_users":        User.objects.count(),
            "active_users":       User.objects.filter(is_active=True).count(),
            "online_users":       User.objects.filter(is_online=True).count(),
            "advocates_total":    User.objects.filter(is_advocate=True).count(),
            "advocates_pending":  User.objects.filter(advocate_status='pending').count(),
            "advocates_approved": User.objects.filter(advocate_status='approved').count(),
            "total_posts":        Post.objects.count(),
            "total_channels":     Channel.objects.count(),
            "total_messages":     Message.objects.count(),
            "total_hearings":     Hearing.objects.count(),
            "new_users_30d":      User.objects.filter(date_joined__gte=last30).count(),
            "new_posts_30d":      Post.objects.filter(created_at__gte=last30).count(),
            "pending_reports":    Report.objects.filter(status='pending').count(),
        })


class AdminChannelListView(generics.ListAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset           = Channel.objects.all().order_by('-created_at')


class AdminLegalUpdateView(generics.ListCreateAPIView):
    """
    Admin: Create/list legal updates for home screen Recent Updates.
    GET/POST /api/admin/legal-updates/
    """
    serializer_class   = LegalUpdateSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset           = LegalUpdate.objects.all().order_by('-created_at')