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
import uuid as _uuid
import boto3
from botocore.config import Config as BotoConfig
from django.conf import settings

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
    Channel, SubChannel, ChannelMembership, ChannelPost, ChannelPostComment, ChannelPostLike, ChannelPostReaction,
    Post, PostReaction, PostComment, Hashtag, SavedPost, PostShare,
    CaseGroup, GroupMembership, GroupDocument,
    Notification, Report,
    Hearing, LegalUpdate,
)
from .serializers import (
    RegisterSerializer, LoginSerializer, OTPVerifySerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, ChangePasswordSerializer,
    UserProfileSerializer, UserMiniSerializer, AdminUserSerializer, AdminAdvocateVerifySerializer,
    AdvocateProfileSerializer, AdvocateVerificationSerializer,
    AdvocateEducationSerializer, AdvocateExperienceSerializer, AdvocateAchievementSerializer,
    ConnectionSerializer, ConnectionRequestSerializer, FollowSerializer,
    ChatRoomSerializer, MessageSerializer, CreateDirectChatSerializer, CreateGroupChatSerializer,
    ChannelSerializer, SubChannelSerializer, ChannelPostSerializer, ChannelPostCommentSerializer,
    ChannelPostReactionSerializer,
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
from .msg91_utils import send_phone_otp, verify_phone_otp, resend_phone_otp

logger = logging.getLogger(__name__)
User = get_user_model()


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════════════


def _normalize_phone(phone: str) -> str:
    """
    Phone number normalize karo storage ke liye.
    Returns: +919876543210 format
    """
    phone = phone.strip().replace(' ', '').replace('-', '')
    if not phone.startswith('+'):
        if phone.startswith('0'):
            phone = '+91' + phone[1:]
        elif len(phone) == 10:
            phone = '+91' + phone
        elif phone.startswith('91') and len(phone) == 12:
            phone = '+' + phone
    return phone


def _make_login_response(user) -> dict:
    """JWT tokens + user data response banao."""
    refresh = RefreshToken.for_user(user)

    onboarding_complete = False
    try:
        onboarding_complete = user.advocate_profile.onboarding_complete
    except Exception:
        pass

    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': {
            'id': str(user.id),
            'username': user.username,
            'email': user.email or '',
            'full_name': user.full_name,
            'phone': str(user.phone) if user.phone else '',
            'is_verified': user.is_verified,
            'is_advocate': user.is_advocate,
            'advocate_status': getattr(user, 'advocate_status', 'none'),
            'onboarding_complete': onboarding_complete,
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# VIEW 1: OTP Send (Login + Signup dono ke liye)
# ══════════════════════════════════════════════════════════════════════════════

class SendPhoneOTPView(APIView):
    """
    POST /api/auth/send-phone-otp/
    Body: {"phone": "9876543210"}

    Response:
        200: {"message": "OTP sent.", "is_new_user": true/false}
        400: {"error": "..."}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone = request.data.get('phone', '').strip()

        if not phone:
            return Response(
                {'error': 'Phone number required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Minimum validation — 10 digit ya +91 format
        clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        if not clean.isdigit() or len(clean) < 10:
            return Response(
                {'error': 'Invalid phone number.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # MSG91 OTP bhejo
        result = send_phone_otp(phone)
        if not result['success']:
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        normalized = _normalize_phone(phone)
        is_new_user = not User.objects.filter(phone=normalized).exists()

        return Response({
            'message': f'OTP sent to {phone}.',
            'is_new_user': is_new_user,
        }, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW 2: Phone OTP se Login (existing user)
# ══════════════════════════════════════════════════════════════════════════════

class VerifyPhoneOTPView(APIView):
    """
    POST /api/auth/verify-phone-otp/
    Body: {"phone": "9876543210", "otp": "123456"}

    Response (existing user):
        200: {access, refresh, user: {...}}
    Response (new user — abhi register nahi):
        404: {"error": "No account found.", "is_new_user": true}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone = request.data.get('phone', '').strip()
        otp   = request.data.get('otp', '').strip()

        if not phone or not otp:
            return Response(
                {'error': 'Phone and OTP both required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # MSG91 OTP verify karo
        result = verify_phone_otp(phone, otp)
        if not result['success']:
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        normalized = _normalize_phone(phone)
        try:
            user = User.objects.get(phone=normalized)
        except User.DoesNotExist:
            return Response(
                {
                    'error': 'No account found with this number. Please sign up.',
                    'is_new_user': True,
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # Phone number verify mark karo
        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=['is_verified'])

        return Response(_make_login_response(user), status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW 3: Phone + OTP se Register (new user)
# ══════════════════════════════════════════════════════════════════════════════

class RegisterWithPhoneView(APIView):
    """
    POST /api/auth/register-phone/
    Body:
        {
            "phone": "9876543210",
            "otp": "123456",
            "full_name": "Arjun Sharma",
            "username": "arjun_sharma_adv",
            "email": "arjun@example.com",       ← optional
            "password": "securepass123",
            "password2": "securepass123"
        }

    Response:
        201: {access, refresh, user, message}
        400: {error}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone     = request.data.get('phone', '').strip()
        full_name = request.data.get('full_name', '').strip()
        username  = request.data.get('username', '').strip()
        email     = (request.data.get('email') or '').strip()  # None-safe: Flutter null → empty string
        password  = request.data.get('password', '')
        password2 = request.data.get('password2', '')

        # ── Validation ────────────────────────────────────────────────────
        # NOTE: OTP yahan dobara verify NAHI hota — signup flow mein Step 2 pe
        # verifyPhoneOtpOnly() already verify kar chuka hai (MSG91 OTP one-time use hai).
        # Dobara verify karne se "already verified" error aata hai.
        errors = {}
        if not phone:
            errors['phone'] = 'Phone number required.'
        if not full_name:
            errors['full_name'] = 'Full name required.'
        if not username:
            errors['username'] = 'Username required.'
        if not password or len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'
        if password != password2:
            errors['password2'] = 'Passwords do not match.'

        if errors:
            return Response({'error': errors}, status=status.HTTP_400_BAD_REQUEST)

        # ── OTP already verified in Step 2 (verifyPhoneOtpOnly) ──────────
        # No re-verification needed here. Phone is trusted.

        normalized = _normalize_phone(phone)

        # Duplicate checks
        if User.objects.filter(phone=normalized).exists():
            return Response(
                {'error': 'An account with this phone number already exists.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if User.objects.filter(username__iexact=username).exists():
            return Response(
                {'error': 'This username is already taken.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if email and User.objects.filter(email__iexact=email).exists():
            return Response(
                {'error': 'An account with this email already exists.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── User Create ───────────────────────────────────────────────────
        user = User.objects.create_user(
            username=username.lower(),
            email=email or None,
            full_name=full_name,
            password=password,
        )
        user.phone = normalized
        user.is_verified = True   # Phone OTP se verify ho gaya
        user.save(update_fields=['phone', 'is_verified'])

        # ✅ FIX: AdvocateProfile auto-create karo — bina iske user network mein nahi dikhega
        AdvocateProfile.objects.get_or_create(user=user)

        return Response({
            'message': 'Account created successfully!',
            'onboarding_complete': False,
            **_make_login_response(user),
        }, status=status.HTTP_201_CREATED)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW 4: OTP Resend
# ══════════════════════════════════════════════════════════════════════════════

class ResendPhoneOTPView(APIView):
    """
    POST /api/auth/resend-phone-otp/
    Body: {"phone": "9876543210"}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone = request.data.get('phone', '').strip()

        if not phone:
            return Response(
                {'error': 'Phone number required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = resend_phone_otp(phone)
        if not result['success']:
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': f'OTP resent to {phone}.'}, status=status.HTTP_200_OK)

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

        # ✅ FIX: Har naye user ka AdvocateProfile auto-create karo
        # Bina iske user suggested/search mein nahi dikhega
        AdvocateProfile.objects.get_or_create(user=user)

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
    """
    GET /api/users/<id>/
    Blocked user ka profile return nahi karta — 404 deta hai.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = User.objects.filter(is_active=True)

    def retrieve(self, request, *args, **kwargs):
        from rest_framework.exceptions import NotFound
        instance = self.get_object()
        is_blocked = Connection.objects.filter(
            Q(sender=request.user, receiver=instance, status='blocked') |
            Q(sender=instance, receiver=request.user, status='blocked')
        ).exists()
        if is_blocked:
            raise NotFound("User not found.")
        return super().retrieve(request, *args, **kwargs)


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
        # Who Can — Flutter Settings > Privacy section se aata hai
        'who_can_message', 'who_can_see_profile',
    ]

    WHO_CAN_VALID = {'everyone', 'connections', 'nobody'}

    def patch(self, request):
        user = request.user
        updated = {}
        errors = {}

        for field in self.ALLOWED_FIELDS:
            if field not in request.data:
                continue
            val = request.data[field]
            # who_can_* fields ke liye valid choices enforce karo
            if field in ('who_can_message', 'who_can_see_profile'):
                if val not in self.WHO_CAN_VALID:
                    errors[field] = f"Invalid value '{val}'. Choose from: {', '.join(self.WHO_CAN_VALID)}"
                    continue
            setattr(user, field, val)
            updated[field] = val

        if errors:
            return Response({'error': 'Invalid values.', 'details': errors}, status=400)

        if not updated:
            return Response({"error": "No valid preference fields provided."}, status=400)

        user.save(update_fields=list(updated.keys()))
        return Response({"message": "Preferences updated.", "updated": updated})




# ══════════════════════════════════════════════════════════════════════════════
# BLOCK / UNBLOCK — Privacy enforcement
# Flutter: Settings > Privacy > Blocked Users
#          AdvocateDetailScreen > ⋮ menu > Block User
# ══════════════════════════════════════════════════════════════════════════════

class BlockedUsersListView(APIView):
    """
    GET /api/users/blocked/
    Apne blocked users ki list return karo.
    Flutter: Settings > Privacy > Blocked Users sheet
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        blocked_ids = Connection.objects.filter(
            sender=request.user,
            status='blocked'
        ).values_list('receiver_id', flat=True)

        blocked_users = User.objects.filter(id__in=blocked_ids)
        serializer = UserMiniSerializer(blocked_users, many=True)
        return Response(serializer.data)


class BlockUserView(APIView):
    """
    POST   /api/users/<uuid:pk>/block/   → User ko block karo
    DELETE /api/users/<uuid:pk>/block/   → User ko unblock karo

    Block logic:
    - Agar sender→receiver connection exist karta hai → status 'blocked' set karo
    - Agar nahi exist karta → naya 'blocked' Connection create karo
    - Reverse connection (receiver→sender) bhi remove karo (bilateral clean-up)

    Flutter: AdvocateDetailScreen > ⋮ > Block User
             Settings > Privacy > Blocked Users > Unblock
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Block a user."""
        target = get_object_or_404(User, pk=pk)

        if target == request.user:
            return Response(
                {"error": "Aap khud ko block nahi kar sakte."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # sender → receiver: block set karo (upsert)
        conn, created = Connection.objects.get_or_create(
            sender=request.user,
            receiver=target,
            defaults={'status': 'blocked'}
        )
        if not created and conn.status != 'blocked':
            conn.status = 'blocked'
            conn.save(update_fields=['status', 'updated_at'])

        # Reverse connection hata do (target ka request bhi remove)
        Connection.objects.filter(
            sender=target,
            receiver=request.user
        ).exclude(status='blocked').delete()

        return Response(
            {
                "message": f"{target.full_name} ko block kar diya gaya.",
                "blocked": True,
                "user_id": str(target.id),
            },
            status=status.HTTP_200_OK
        )

    def delete(self, request, pk):
        """Unblock a user."""
        target = get_object_or_404(User, pk=pk)

        deleted_count, _ = Connection.objects.filter(
            sender=request.user,
            receiver=target,
            status='blocked'
        ).delete()

        if deleted_count == 0:
            return Response(
                {"error": "Yeh user block nahi tha."},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {
                "message": f"{target.full_name} ko unblock kar diya gaya.",
                "blocked": False,
                "user_id": str(target.id),
            },
            status=status.HTTP_200_OK
        )


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

        # Real-time connection count — cached field pe rely nahi karte.
        # Race condition aur desync se bachne ke liye direct DB query.
        connection_count = Connection.objects.filter(
            Q(sender=user) | Q(receiver=user),
            status='accepted'
        ).count()

        # Cached field bhi opportunistically sync rakhte hain
        # taaki profile screen bhi consistent rahe.
        try:
            profile = user.advocate_profile
            if profile.connection_count != connection_count:
                profile.connection_count = connection_count
                profile.save(update_fields=['connection_count'])
        except AdvocateProfile.DoesNotExist:
            pass

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
    search_fields = ['user__full_name', 'user__username', 'bio', 'city', 'state',
                     'specializations', 'state_bar_council']
    ordering_fields = ['years_of_experience', 'connection_count', 'follower_count']
    ordering = ['-connection_count']

    def get_queryset(self):
        # ── Blocked users exclude karo (dono directions) ──────────────────────
        # 1. Jin users ko current user ne block kiya
        # 2. Jin users ne current user ko block kiya
        blocked_by_me = Connection.objects.filter(
            sender=self.request.user, status='blocked'
        ).values_list('receiver_id', flat=True)

        blocked_me = Connection.objects.filter(
            receiver=self.request.user, status='blocked'
        ).values_list('sender_id', flat=True)

        excluded_ids = set(list(blocked_by_me) + list(blocked_me))

        qs = AdvocateProfile.objects.filter(
            user__is_active=True,
        ).exclude(
            user__id__in=excluded_ids  # ← Block filter
        ).select_related('user').prefetch_related('education', 'experience', 'achievements')

        # ✅ FIX: Flutter ?name= query param bhi handle karo (not just DRF ?search=)
        name = self.request.query_params.get('name', '').strip()
        if name:
            qs = qs.filter(
                Q(user__full_name__icontains=name) |
                Q(user__username__icontains=name) |
                Q(city__icontains=name) |
                Q(state__icontains=name)
            )

        # Other filters from Flutter
        city = self.request.query_params.get('city', '').strip()
        if city:
            qs = qs.filter(city__icontains=city)

        state = self.request.query_params.get('state', '').strip()
        if state:
            qs = qs.filter(state__icontains=state)

        practice_area = self.request.query_params.get('practice_area', '').strip()
        if practice_area:
            qs = qs.filter(specializations__icontains=practice_area)

        court = self.request.query_params.get('court', '').strip()
        if court:
            qs = qs.filter(
                Q(primary_court__icontains=court) |
                Q(courts_practiced__icontains=court)
            )

        language = self.request.query_params.get('language', '').strip()
        if language:
            qs = qs.filter(languages_known__icontains=language)

        min_exp = self.request.query_params.get('min_exp')
        if min_exp:
            try:
                qs = qs.filter(years_of_experience__gte=int(min_exp))
            except ValueError:
                pass

        max_exp = self.request.query_params.get('max_exp')
        if max_exp:
            try:
                qs = qs.filter(years_of_experience__lte=int(max_exp))
            except ValueError:
                pass

        return qs


class MyAdvocateProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return profile

    def update(self, request, *args, **kwargs):
        """
        PATCH /api/advocates/me/

        profile_photo_url / cover_photo_url -> URLField mein save hoga (Cloudinary/R2 URL).
        years_of_experience alias 'experience_years' bhi accept karta hai (Flutter compat).
        cases_handled -> User model pe save hota hai (AdvocateProfile mein nahi).
        """
        profile = self.get_object()

        # Mutable dict banao — QueryDict se bhi kaam kare
        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)

        # URL aliases — Flutter in keys se bhejta hai
        if data.get('profile_photo_url'):
            data['profile_photo'] = data.pop('profile_photo_url')

        if data.get('cover_photo_url'):
            data['cover_photo'] = data.pop('cover_photo_url')

        # experience_years alias (Flutter edit screen se aata hai)
        if 'experience_years' in data and 'years_of_experience' not in data:
            data['years_of_experience'] = data.pop('experience_years')

        # cases_handled — User model ka field hai, AdvocateProfile ka nahi
        cases_handled = data.pop('cases_handled', None)
        if cases_handled is not None:
            try:
                request.user.cases_handled = int(cases_handled)
                request.user.save(update_fields=['cases_handled'])
            except (ValueError, TypeError):
                pass

        serializer = self.get_serializer(profile, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


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
    """
    GET /api/advocates/<user_id>/
    Blocked users ka profile nahi dikhata — 404 return karta hai.
    """
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        from rest_framework.exceptions import NotFound
        user = get_object_or_404(User, id=self.kwargs['user_id'], is_active=True)

        # ── Block check ───────────────────────────────────────────────────────
        is_blocked = Connection.objects.filter(
            Q(sender=self.request.user, receiver=user, status='blocked') |
            Q(sender=user, receiver=self.request.user, status='blocked')
        ).exists()
        if is_blocked:
            raise NotFound("Profile not found.")

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


class SentConnectionsView(generics.ListAPIView):
    serializer_class   = ConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Apne bheje hue pending requests — jo abhi accept/reject nahi hue
        return Connection.objects.filter(
            sender=self.request.user, status='pending'
        ).select_related('receiver')


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
            # ✅ FIX: Duplicate click pe 400 error nahi — existing pending conn return karo
            # Flutter side "error" parse karke crash karta tha, ab silently succeed karta hai
            return Response(
                ConnectionSerializer(existing, context={'request': request}).data,
                status=200
            )

        conn = Connection.objects.create(
            sender=request.user,
            receiver=receiver,
            message=serializer.validated_data.get('message', ''),
        )

        # ✅ FIX: Email synchronous tha — ASGI timeout ka root cause yahi tha
        # transaction.on_commit se email request complete hone ke BAAD bheja jaata hai
        try:
            from django.db import transaction
            _sender = request.user
            _receiver = receiver
            transaction.on_commit(lambda: _send_connection_email_bg(_sender, _receiver))
        except Exception:
            pass

        create_notification(
            recipient=receiver, notif_type='connection_request',
            title='New Connection Request',
            body=f"{request.user.full_name} sent you a connection request.",
            sender=request.user,
        )
        return Response(ConnectionSerializer(conn, context={'request': request}).data, status=201)


def _send_connection_email_bg(sender, receiver):
    """Email ko background mein bhejo — request thread block nahi hogi"""
    try:
        send_connection_request_email(sender, receiver)
    except Exception:
        pass  # Email fail = silent fail, connection already created hai


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
        # F() expression use karo — read-modify-write race condition se bachta hai
        from django.db.models import F
        for user in [conn.sender, conn.receiver]:
            AdvocateProfile.objects.filter(user=user).update(
                connection_count=F('connection_count') + 1
            )

    def _decrement_connection_counts(self, conn):
        from django.db.models import F
        from django.db.models.functions import Greatest
        for user in [conn.sender, conn.receiver]:
            # Greatest(count-1, 0) ensures never goes negative
            AdvocateProfile.objects.filter(user=user).update(
                connection_count=Greatest(F('connection_count') - 1, 0)
            )


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
        # ✅ Sirf ACCEPTED connections exclude karo — pending wale tab bhi dikhne chahiye
        accepted_connections = Connection.objects.filter(
            Q(sender=self.request.user) | Q(receiver=self.request.user),
            status='accepted'
        ).values_list('sender_id', 'receiver_id')
        excluded = set()
        for s, r in accepted_connections:
            excluded.add(s)
            excluded.add(r)
        excluded.add(self.request.user.id)

        # ── Blocked users bhi exclude karo ───────────────────────────────────
        blocked_by_me = Connection.objects.filter(
            sender=self.request.user, status='blocked'
        ).values_list('receiver_id', flat=True)
        blocked_me = Connection.objects.filter(
            receiver=self.request.user, status='blocked'
        ).values_list('sender_id', flat=True)
        excluded.update(blocked_by_me)
        excluded.update(blocked_me)

        return AdvocateProfile.objects.filter(
            user__is_active=True,
        ).exclude(user__id__in=excluded).order_by('?')[:50]


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

        # ── who_can_message enforcement ───────────────────────────────────────
        # Agar target ne 'nobody' set kiya hai → room create mat karo
        if other.who_can_message == 'nobody':
            return Response(
                {"error": f"{other.full_name} ne messages band kar rakhe hain."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Agar target ne 'connections' set kiya hai → connected hona zaroori hai
        if other.who_can_message == 'connections':
            is_connected = Connection.objects.filter(
                Q(sender=request.user, receiver=other) |
                Q(sender=other, receiver=request.user),
                status='accepted'
            ).exists()
            if not is_connected:
                return Response(
                    {"error": f"{other.full_name} sirf connections se messages accept karte hain."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # ── blocked check ─────────────────────────────────────────────────────
        # Agar other ne request.user ko block kiya hai → room create mat karo
        is_blocked = Connection.objects.filter(
            sender=other, receiver=request.user, status='blocked'
        ).exists()
        if is_blocked:
            return Response(
                {"error": "Yeh user available nahi hai."},
                status=status.HTTP_403_FORBIDDEN
            )

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

        # Newest messages pehle fetch karo, phir reverse taaki chronological order mile
        # page=1 → latest 50, page=2 → 51-100 etc.
        messages_qs = (
            Message.objects
            .filter(room=room, is_deleted=False)
            .select_related('sender')
            .prefetch_related('read_receipts')
            .order_by('-created_at')   # newest first for slicing
        )
        total = messages_qs.count()
        start = (page - 1) * page_size
        end   = start + page_size
        page_msgs = list(messages_qs[start:end])
        page_msgs.reverse()            # chronological order restore karo for Flutter

        has_next = end < total         # aur purane messages hain?
        ChatParticipant.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        return Response({
            "count": total,
            "next": f"?page={page + 1}" if has_next else None,
            "previous": f"?page={page - 1}" if page > 1 else None,
            "results": MessageSerializer(page_msgs, many=True, context={'request': request}).data,
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
        # FIXED: is_private=False filter hataya — private channels bhi search mein dikhenge
        # Flutter side pe private channels ke liye "Request to Join" button dikhaega
        return Channel.objects.all().prefetch_related('sub_channels')


class MyChannelsView(generics.ListAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # sirf active memberships — pending join requests exclude karo
        return Channel.objects.filter(
            memberships__user=self.request.user,
            memberships__status='active',
        ).prefetch_related('sub_channels').distinct()


class ChannelDetailView(generics.RetrieveAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset           = Channel.objects.prefetch_related('sub_channels')
    lookup_field       = 'id'


class UpdateChannelView(generics.UpdateAPIView):
    """PATCH /api/channels/<uuid>/ — only channel admin can update"""
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset           = Channel.objects.prefetch_related('sub_channels')
    lookup_field       = 'id'
    http_method_names  = ['patch']  # only PATCH, not PUT

    def get_object(self):
        channel = super().get_object()
        # Only admin members can update
        membership = channel.memberships.filter(
            user=self.request.user, role='admin'
        ).first()
        if not membership:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only channel admins can update this channel.')
        return channel


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

        # FIXED: Auto "General" sub-channel banao with is_default=True
        if not SubChannel.objects.filter(parent=channel, slug='general').exists():
            SubChannel.objects.create(
                parent=channel,
                name='General',
                slug='general',
                description='General discussion',
                is_default=True,
            )


class JoinChannelView(APIView):
    """
    POST /api/channels/<uuid>/join/
    Public channel  → direct join
    Private channel → creates pending join request (admin must approve)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        existing = ChannelMembership.objects.filter(channel=channel, user=request.user).first()
        if existing:
            if existing.status == 'pending':
                return Response({"error": "Join request already pending."}, status=400)
            return Response({"error": "Already a member."}, status=400)

        if channel.is_private:
            # Private channel — create pending membership, notify admin
            membership = ChannelMembership.objects.create(
                channel=channel, user=request.user, role='member', status='pending'
            )
            # Notify channel admin
            admin_membership = channel.memberships.filter(role='admin').first()
            if admin_membership:
                create_notification(
                    recipient=admin_membership.user,
                    sender=request.user,
                    notif_type='channel_update',
                    title=f'Join request: {channel.name}',
                    body=f'{request.user.full_name} wants to join {channel.name}',
                    data={'channel_id': str(channel.id), 'user_id': str(request.user.id)},
                )
            return Response({
                "message": "Join request sent. Waiting for admin approval.",
                "status": "pending"
            }, status=201)
        else:
            ChannelMembership.objects.create(channel=channel, user=request.user, role='member', status='active')
            channel.member_count += 1
            channel.save(update_fields=['member_count'])
            return Response({"message": f"Joined {channel.name}.", "status": "active"}, status=201)


class LeaveChannelView(APIView):
    """
    POST /api/channels/<uuid>/leave/   — Flutter uses POST
    DELETE /api/channels/<uuid>/leave/ — also supported
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        return self._leave(request, pk)

    def delete(self, request, pk):
        return self._leave(request, pk)

    def _leave(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        # Admin apna channel leave nahi kar sakta
        is_admin = channel.memberships.filter(user=request.user, role='admin').exists()
        if is_admin:
            return Response(
                {"error": "Channel admin leave nahi kar sakta. Pehle kisi aur ko admin banao."},
                status=status.HTTP_403_FORBIDDEN,
            )
        deleted, _ = ChannelMembership.objects.filter(channel=channel, user=request.user).delete()
        if deleted:
            channel.member_count = max(0, channel.member_count - 1)
            channel.save(update_fields=['member_count'])
        return Response(status=204)


class ChannelJoinRequestListView(APIView):
    """
    GET  /api/channels/<uuid>/join-requests/     — list pending requests (admin only)
    POST /api/channels/<uuid>/join-requests/<user_id>/approve/  — approve
    POST /api/channels/<uuid>/join-requests/<user_id>/reject/   — reject
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        # Only admin can see requests
        if not channel.memberships.filter(user=request.user, role='admin').exists():
            return Response({"error": "Only admins can view join requests."}, status=403)
        pending = ChannelMembership.objects.filter(channel=channel, status='pending').select_related('user')
        data = [
            {
                "user_id": str(m.user.id),
                "full_name": m.user.full_name,
                "username": m.user.username,
                "requested_at": m.joined_at.isoformat(),
            }
            for m in pending
        ]
        return Response(data)


class ChannelJoinRequestActionView(APIView):
    """
    POST /api/channels/<uuid>/join-requests/<user_id>/approve/
    POST /api/channels/<uuid>/join-requests/<user_id>/reject/
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, user_id, action):
        channel = get_object_or_404(Channel, id=pk)
        if not channel.memberships.filter(user=request.user, role='admin').exists():
            return Response({"error": "Only admins can approve/reject requests."}, status=403)

        membership = get_object_or_404(ChannelMembership, channel=channel, user_id=user_id, status='pending')
        target_user = membership.user

        if action == 'approve':
            membership.status = 'active'
            membership.save(update_fields=['status'])
            channel.member_count += 1
            channel.save(update_fields=['member_count'])
            create_notification(
                recipient=target_user,
                sender=request.user,
                notif_type='channel_update',
                title=f'Request approved: {channel.name}',
                body=f'You have been approved to join {channel.name}',
                data={'channel_id': str(channel.id)},
            )
            return Response({"message": "Request approved."})
        elif action == 'reject':
            membership.delete()
            create_notification(
                recipient=target_user,
                sender=request.user,
                notif_type='channel_update',
                title=f'Request declined: {channel.name}',
                body=f'Your request to join {channel.name} was declined.',
                data={'channel_id': str(channel.id)},
            )
            return Response({"message": "Request rejected."})
        else:
            return Response({"error": "Invalid action."}, status=400)


class ChannelIconPresignView(APIView):
    """
    POST /api/channels/icon-presign/
    Flutter se seedha R2 pe channel icon/cover upload ke liye presigned URL.
    Body: { file_name, mime_type, upload_type: 'icon'|'cover' }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        file_name   = request.data.get('file_name', 'channel_icon.jpg')
        mime_type   = request.data.get('mime_type', 'image/jpeg')
        upload_type = request.data.get('upload_type', 'icon')  # 'icon' or 'cover'

        try:
            r2 = boto3.client(
                's3',
                endpoint_url=settings.R2_ENDPOINT_URL,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=BotoConfig(signature_version='s3v4'),
                region_name='auto',
            )
            unique_name = f"channel_{upload_type}s/{_uuid.uuid4()}_{file_name}"
            upload_url = r2.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.R2_BUCKET_NAME,
                    'Key': unique_name,
                    'ContentType': mime_type,
                },
                ExpiresIn=300,
            )
            file_url = f"{settings.R2_PUBLIC_URL}/{unique_name}"
            return Response({'upload_url': upload_url, 'file_url': file_url})
        except Exception as e:
            logger.error(f"Channel icon presign error: {e}")
            return Response({'error': 'Failed to generate upload URL.'}, status=500)


class ChannelPostPresignView(APIView):
    """
    POST /api/channels/<uuid>/posts/presign/
    Flutter se direct R2 upload ke liye presigned URL (channel post attachment).
    Body: { file_name, mime_type }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, channel_id):
        channel = get_object_or_404(Channel, id=channel_id)
        if not channel.memberships.filter(user=request.user, status='active').exists():
            return Response({'error': 'You must be a member to post.'}, status=403)

        file_name = request.data.get('file_name', 'attachment.jpg')
        mime_type = request.data.get('mime_type', 'image/jpeg')

        try:
            # Use same R2 settings as chat presign (R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, etc.)
            r2 = boto3.client(
                's3',
                endpoint_url=settings.R2_ENDPOINT_URL,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=BotoConfig(signature_version='s3v4'),
                region_name='auto',
            )
            ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
            uid = _uuid.uuid4().hex
            unique_name = f"channel_attachments/{channel_id}/{uid}.{ext}" if ext else f"channel_attachments/{channel_id}/{uid}"
            upload_url = r2.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.R2_BUCKET_NAME,
                    'Key': unique_name,
                    'ContentType': mime_type,
                },
                ExpiresIn=300,
            )
            file_url = f"{settings.R2_PUBLIC_URL.rstrip('/')}/{unique_name}"
            return Response({'upload_url': upload_url, 'file_url': file_url})
        except Exception as e:
            logger.error(f"Channel post presign error: {e}")
            return Response({'error': 'Failed to generate upload URL.'}, status=500)


class ChannelMembersListView(generics.ListAPIView):
    """
    GET /api/channels/<channel_id>/members/
    Returns all active members of a channel with their user info and role.
    Only accessible by channel members.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, channel_id):
        channel = get_object_or_404(Channel, id=channel_id)

        # Only members can see the member list
        is_member = ChannelMembership.objects.filter(
            channel=channel, user=request.user, status='active'
        ).exists()
        if not is_member and not channel.is_official:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You must be a member to view the member list.")

        memberships = ChannelMembership.objects.filter(
            channel=channel
        ).select_related('user').order_by('role', 'joined_at')

        data = []
        for m in memberships:
            u = m.user
            profile_photo = None
            if hasattr(u, 'profile_photo') and u.profile_photo:
                try:
                    profile_photo = request.build_absolute_uri(u.profile_photo.url)
                except Exception:
                    pass
            data.append({
                'membership_id': str(m.id) if hasattr(m, 'id') else None,
                'role': m.role,
                'status': m.status,
                'joined_at': m.joined_at.isoformat() if m.joined_at else None,
                'is_muted': m.is_muted,
                'user': {
                    'id': str(u.id),
                    'full_name': getattr(u, 'full_name', '') or u.username,
                    'username': u.username,
                    'email': u.email,
                    'profile_photo': profile_photo,
                    'is_advocate': getattr(u, 'is_advocate', False),
                    'advocate_status': getattr(u, 'advocate_status', None),
                    'presence_status': getattr(u, 'presence_status', 'offline'),
                },
            })

        return Response(data)


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
        return SubChannel.objects.filter(parent=channel, is_active=True).order_by('-is_default', 'created_at')

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

        # FIXED: is_default sirf tab True ho jab explicitly pass kiya jaye
        is_default = serializer.validated_data.get('is_default', False)

        # Agar is_default=True hai, pehle se jo default tha use False karo
        if is_default:
            SubChannel.objects.filter(parent=channel, is_default=True).update(is_default=False)

        serializer.save(parent=channel, slug=slug, is_default=is_default)


class SetDefaultSubChannelView(APIView):
    """
    POST /api/channels/<channel_id>/sub-channels/<sub_id>/set-default/
    Admin apni marzi se kisi bhi sub-channel ko default set kar sakta hai.
    Pehle jo default tha wo automatically unset ho jaata hai.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, channel_id, sub_id):
        channel = get_object_or_404(Channel, id=channel_id)

        # Only admin can set default
        if not channel.memberships.filter(user=request.user, role='admin').exists():
            return Response({"error": "Only admins can set the default sub-channel."}, status=403)

        sub = get_object_or_404(SubChannel, id=sub_id, parent=channel, is_active=True)

        # Pehle sab ka is_default False karo
        SubChannel.objects.filter(parent=channel, is_default=True).update(is_default=False)

        # Ab is sub-channel ko default banao
        sub.is_default = True
        sub.save(update_fields=['is_default'])

        return Response({
            "message": f"'{sub.name}' is now the default sub-channel.",
            "sub_channel_id": str(sub.id),
            "is_default": True,
        })


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
        channel = get_object_or_404(Channel, id=self.kwargs['channel_id'])
        # Check membership (active only — not pending)
        if not channel.memberships.filter(user=self.request.user, status='active').exists():
            # Also allow channel creator even without active membership row
            if channel.created_by != self.request.user:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('You must be an active member to post.')

        # Support two attachment modes:
        # 1. Direct file upload (FormData) — old way
        # 2. R2 URL string — new way (Flutter uploads to R2 directly, sends URL)
        attachment = self.request.FILES.get('attachment')
        attachment_url_r2 = self.request.data.get('attachment_url')  # R2 public URL

        att_type = ''
        if attachment:
            att_type = get_file_type(attachment)
        elif attachment_url_r2:
            # Detect type from URL extension
            url_lower = attachment_url_r2.lower()
            if any(url_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                att_type = 'image'
            elif url_lower.endswith('.pdf'):
                att_type = 'pdf'
            elif any(url_lower.endswith(ext) for ext in ['.mp4', '.mov', '.webm']):
                att_type = 'video'
            else:
                att_type = self.request.data.get('attachment_type', 'file')

        sub_channel_id = self.request.data.get('sub_channel')
        sub_channel = None
        if sub_channel_id:
            sub_channel = SubChannel.objects.filter(id=sub_channel_id, parent=channel).first()

        save_kwargs = dict(
            author=self.request.user,
            channel=channel,
            attachment_type=att_type,
            sub_channel=sub_channel,
        )
        if attachment_url_r2:
            # R2 URL directly store karo
            save_kwargs['attachment_url'] = attachment_url_r2
        elif attachment:
            # Legacy direct file upload (fallback) — store URL if possible
            save_kwargs['attachment_url'] = None  # direct file upload deprecated

        serializer.save(**save_kwargs)


class ChannelPostLikeView(APIView):
    """
    POST /api/channels/posts/<uuid>/like/
    Telegram-style reaction toggle.
    Body: { "reaction_type": "like" | "love" | "insightful" | "celebrate" | "support" }
    - Same reaction type → toggle off (remove reaction)
    - Different reaction type → switch to new reaction
    - No existing reaction → add new reaction
    Response: { "is_liked": bool, "like_count": int, "user_reaction": str|null,
                "reactions_summary": { "like": N, "love": N, ... } }
    """
    permission_classes = [permissions.IsAuthenticated]

    VALID_TYPES = {'like', 'love', 'insightful', 'celebrate', 'support'}

    def post(self, request, pk):
        post = get_object_or_404(ChannelPost, id=pk)
        reaction_type = (request.data.get('reaction_type') or 'like').strip().lower()

        if reaction_type not in self.VALID_TYPES:
            return Response(
                {'error': f'Invalid reaction_type. Choose from: {", ".join(self.VALID_TYPES)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = ChannelPostReaction.objects.filter(post=post, user=request.user).first()

        if existing:
            if existing.reaction_type == reaction_type:
                # Same reaction → toggle off (remove)
                existing.delete()
                post.like_count = max(0, ChannelPostReaction.objects.filter(post=post).count())
                post.save(update_fields=['like_count'])
                user_reaction = None
                is_liked = False
            else:
                # Different reaction → switch
                existing.reaction_type = reaction_type
                existing.save(update_fields=['reaction_type'])
                user_reaction = reaction_type
                is_liked = True
        else:
            # New reaction
            ChannelPostReaction.objects.create(post=post, user=request.user, reaction_type=reaction_type)
            post.like_count = ChannelPostReaction.objects.filter(post=post).count()
            post.save(update_fields=['like_count'])
            user_reaction = reaction_type
            is_liked = True

        # Telegram-style summary
        from django.db.models import Count
        summary = {
            row['reaction_type']: row['count']
            for row in ChannelPostReaction.objects.filter(post=post)
                .values('reaction_type').annotate(count=Count('id'))
        }

        return Response({
            'is_liked':          is_liked,
            'like_count':        post.like_count,
            'user_reaction':     user_reaction,
            'reactions_summary': summary,
        })


class ChannelPostCommentView(generics.ListCreateAPIView):
    """
    GET  /api/channels/posts/<post_id>/comments/  — list top-level comments with replies
    POST /api/channels/posts/<post_id>/comments/  — add comment
    Body: { "content": "...", "parent": "<uuid>" (optional for replies) }
    """
    serializer_class   = ChannelPostCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Sirf top-level comments (parent=None) return karo — replies nested hain
        return ChannelPostComment.objects.filter(
            post_id=self.kwargs['post_id'], parent=None,
        ).select_related('author').prefetch_related('replies__author')

    def perform_create(self, serializer):
        post = get_object_or_404(ChannelPost, id=self.kwargs['post_id'])

        # parent UUID resolve karo agar reply hai
        parent_id = self.request.data.get('parent')
        parent = None
        if parent_id:
            parent = ChannelPostComment.objects.filter(id=parent_id, post=post).first()

        serializer.save(author=self.request.user, post=post, parent=parent)
        post.comment_count = ChannelPostComment.objects.filter(post=post).count()
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
        data = self.request.data

        # Media: FILE upload (legacy) > R2 URL string (new flow)
        file = self.request.FILES.get('media')
        if file:
            media_value = file
            media_type  = get_file_type(file)
        else:
            url = (data.get('media') or '').strip()
            media_value = url if url.startswith('http') else None
            media_type  = (data.get('media_type') or '').strip()

        post = serializer.save(
            author=self.request.user,
            media=media_value,
            media_type=media_type,
        )

        # Hashtags — Flutter sends 'hashtags' key, serializer has 'hashtag_names'
        # Try both sources
        hashtag_names = serializer.validated_data.get('hashtag_names', [])

        if not hashtag_names:
            raw = data.get('hashtags') or data.get('hashtag_names') or []
            if not raw and hasattr(data, 'getlist'):
                raw = data.getlist('hashtags') or data.getlist('hashtag_names')
            if isinstance(raw, str):
                raw = [raw]
            hashtag_names = raw

        for name in hashtag_names:
            if not isinstance(name, str):
                continue
            name = name.strip().lstrip('#').lower()
            if name:
                tag, _ = Hashtag.objects.get_or_create(name=name)
                post.hashtags.add(tag)
                tag.post_count = tag.post_count + 1
                tag.save(update_fields=['post_count'])

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

class ChatRoomDetailView(generics.RetrieveAPIView):
    """
    GET /api/chat/rooms/<room_id>/
    Single room fetch — direct navigation ke waqt Flutter use karta hai
    """
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]
 
    def get_object(self):
        room_id = self.kwargs['room_id']
        return get_object_or_404(
            ChatRoom,
            id=room_id,
            room_participants__user=self.request.user
        )

class R2PresignedUploadView(APIView):
    """
    POST /api/chat/presign/
 
    Flutter is view se presigned PUT URL maangta hai.
    Phir file directly R2 pe upload karta hai.
    Backend ko sirf final URL milta hai — zero file bandwidth on backend.
 
    Request body:
        {
          "file_name": "photo.jpg",
          "mime_type": "image/jpeg",
          "room_id":   "<uuid>"
        }
 
    Response:
        {
          "upload_url": "https://...",   ← Flutter yahan PUT karega
          "file_url":   "https://...",   ← Final public URL (WS se bhejo)
          "key":        "chat/<room>/<uuid>.jpg"
        }
    """
    permission_classes = [permissions.IsAuthenticated]
 
    # Allowed MIME types — arbitrary uploads block karo
    ALLOWED_MIMES = {
        # Images
        'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic', 'image/heif',
        # Videos — Android/iOS dono ke common formats
        'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm',
        'video/3gpp', 'video/3gpp2', 'video/mpeg', 'video/x-msvideo',
        # Documents
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        # Audio / Voice
        'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav', 'audio/aac',
        'audio/x-m4a', 'audio/amr',
        # Text
        'text/plain',
    }
 
    def post(self, request):
        file_name = (request.data.get('file_name') or '').strip()
        mime_type = (request.data.get('mime_type') or 'application/octet-stream').strip()
        room_id   = (request.data.get('room_id') or '').strip()
 
        if not file_name or not room_id:
            return Response(
                {'error': 'file_name and room_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        if mime_type not in self.ALLOWED_MIMES:
            return Response(
                {'error': 'File type not allowed'},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # Room participant check — security: sirf room member upload kar sake
        from .models import ChatRoom
        room_qs = ChatRoom.objects.filter(
            id=room_id,
            room_participants__user=request.user,
        )
        if not room_qs.exists():
            return Response(
                {'error': 'Room not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )
 
        # Unique key generate karo: chat/<room_id>/<uuid>.<ext>
        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
        uid = _uuid.uuid4().hex
        key = f"chat/{room_id}/{uid}.{ext}" if ext else f"chat/{room_id}/{uid}"
 
        # R2 client — boto3 S3-compatible
        r2 = boto3.client(
            's3',
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version='s3v4'),
            region_name='auto',
        )
 
        # Presigned PUT URL — 5 min valid
        upload_url = r2.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': settings.R2_BUCKET_NAME,
                'Key': key,
                'ContentType': mime_type,
            },
            ExpiresIn=300,
        )
 
        # Public URL — R2_PUBLIC_URL .env mein set karo
        file_url = f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"
 
        return Response({
            'upload_url': upload_url,
            'file_url':   file_url,
            'key':        key,
        }, status=status.HTTP_200_OK)

class PostMediaPresignView(APIView):
    """
    POST /api/feed/presign/

    Community post ke media ke liye presigned R2 URL.
    Chat presign se alag — room_id UUID nahi chahiye.

    Request: { "file_name": "photo.jpg", "mime_type": "image/jpeg" }
    Response: { "upload_url": "...", "file_url": "...", "key": "..." }
    """
    permission_classes = [permissions.IsAuthenticated]

    ALLOWED_MIMES = {
        'image/jpeg', 'image/png', 'image/webp', 'image/gif',
        'image/heic', 'image/heif',
        'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm',
        'video/3gpp', 'video/mpeg', 'video/x-msvideo',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
    }

    def post(self, request):
        file_name = (request.data.get('file_name') or '').strip()
        mime_type = (request.data.get('mime_type') or 'application/octet-stream').strip()

        if not file_name:
            return Response({'error': 'file_name is required'}, status=status.HTTP_400_BAD_REQUEST)

        if mime_type not in self.ALLOWED_MIMES:
            return Response({'error': 'File type not allowed'}, status=status.HTTP_400_BAD_REQUEST)

        ext    = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
        uid    = _uuid.uuid4().hex
        folder = _uuid.uuid4().hex
        key    = f"posts/{folder}/{uid}.{ext}" if ext else f"posts/{folder}/{uid}"

        r2 = boto3.client(
            's3',
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version='s3v4'),
            region_name='auto',
        )

        upload_url = r2.generate_presigned_url(
            'put_object',
            Params={'Bucket': settings.R2_BUCKET_NAME, 'Key': key, 'ContentType': mime_type},
            ExpiresIn=300,
        )

        file_url = f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"

        return Response({'upload_url': upload_url, 'file_url': file_url, 'key': key})

class PostSearchView(generics.ListAPIView):
    """
    GET /api/feed/search/
    Params:
      q         — search query (required)
      post_type — optional filter (judgment, legal_update, discussion, etc.)
      page      — pagination (default 20 per page)

    Ranking logic (manual scoring, no Postgres full-text needed):
      1. Exact hashtag match  → score +30
      2. Query in content     → score +20 (higher if starts with query)
      3. Query in author name → score +10
      4. Like count boost     → score + (like_count * 0.1), max +10

    Final order: score DESC, created_at DESC (recency tiebreak)
    """
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        query     = (self.request.query_params.get('q') or '').strip()
        post_type = (self.request.query_params.get('post_type') or '').strip()

        # Query aur post_type dono empty hain — kuch mat do
        if not query and not post_type:
            return Post.objects.none()

        # Handle hashtag search: "#SupremeCourt" → search by hashtag
        is_hashtag_search = query.startswith('#')
        clean_query       = query.lstrip('#').lower()

        # Base queryset — only public posts ya apne posts
        qs = Post.objects.filter(
            Q(is_public=True) | Q(author=self.request.user)
        ).select_related('author').prefetch_related('hashtags')

        # Optional post_type filter
        if post_type:
            qs = qs.filter(post_type=post_type)

        # Query filter — sirf tab lagao jab query ho
        if query:
            if is_hashtag_search:
                # Hashtag search — exact match first, then partial
                qs = qs.filter(hashtags__name__icontains=clean_query).distinct()
            else:
                # Full text search: content OR author name OR hashtag name
                qs = qs.filter(
                    Q(content__icontains=clean_query)
                    | Q(author__full_name__icontains=clean_query)
                    | Q(author__username__icontains=clean_query)
                    | Q(hashtags__name__icontains=clean_query)
                ).distinct()

        return qs

    def list(self, request, *args, **kwargs):
        query      = (request.query_params.get('q') or '').strip()
        clean_query = query.lstrip('#').lower()
        queryset    = self.get_queryset()

        # ── Relevance scoring ─────────────────────────────────────────────────
        def score(post):
            s = 0

            # Hashtag exact match → strongest signal
            hashtag_names = [h.name.lower() for h in post.hashtags.all()]
            if clean_query in hashtag_names:
                s += 30
            elif any(clean_query in hn for hn in hashtag_names):
                s += 15

            # Content match
            content_lower = post.content.lower()
            if content_lower.startswith(clean_query):
                s += 25
            elif clean_query in content_lower:
                s += 20

            # Author name match
            if clean_query in post.author.full_name.lower():
                s += 10
            if clean_query in post.author.username.lower():
                s += 8

            # Engagement boost (capped at +10)
            s += min(post.like_count * 0.1, 10)

            return s

        # Score and sort
        posts  = list(queryset)
        scored = sorted(posts, key=lambda p: (-score(p), -p.created_at.timestamp()))

        # Manual pagination
        try:
            page_num  = int(request.query_params.get('page', 1))
        except ValueError:
            page_num  = 1
        page_size = 20
        start     = (page_num - 1) * page_size
        end       = start + page_size
        page_data = scored[start:end]

        serializer = self.get_serializer(page_data, many=True, context={'request': request})
        return Response({
            'count':    len(scored),
            'next':     None if end >= len(scored) else f"?q={query}&page={page_num + 1}",
            'previous': None if page_num <= 1 else f"?q={query}&page={page_num - 1}",
            'results':  serializer.data,
        })

def _is_admin(room, user):
    """Check if user is admin of the room."""
    from .models import ChatParticipant
    return ChatParticipant.objects.filter(
        room=room, user=user, role='admin'
    ).exists()
 
 
def _participant_data(cp):
    """Serialize a ChatParticipant for the member list API."""
    return {
        "id": str(cp.user.id),
        "full_name": cp.user.full_name,
        "username": cp.user.username,
        "avatar": cp.user.avatar.url if hasattr(cp.user, 'avatar') and cp.user.avatar else None,
        "is_online": cp.user.is_online,
        "role": cp.role,          # 'admin' | 'member'
        "joined_at": cp.joined_at.isoformat(),
        "is_muted": cp.is_muted,
    }
 
 
# ── Group Members List ────────────────────────────────────────────────────────
 
class GroupMembersView(APIView):
    """
    GET  /api/chat/rooms/<room_id>/members/
    List all members of a group room.
    User must be a participant.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, room_id):
        from .models import ChatRoom, ChatParticipant
        room = get_object_or_404(
            ChatRoom, id=room_id, room_type='group',
            room_participants__user=request.user
        )
        participants = (
            ChatParticipant.objects
            .filter(room=room)
            .select_related('user')
            .order_by('role', 'joined_at')   # admins first
        )
        return Response({
            "room_id": str(room.id),
            "room_name": room.name,
            "total": participants.count(),
            "members": [_participant_data(cp) for cp in participants],
            "is_admin": _is_admin(room, request.user),
        })
 
 
# ── Add Member ────────────────────────────────────────────────────────────────
 
class GroupAddMemberView(APIView):
    """
    POST /api/chat/rooms/<room_id>/members/add/
    Body: { "user_ids": ["uuid1", "uuid2"] }
    Only group admins can add members.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, room_id):
        from .models import ChatRoom, ChatParticipant
        room = get_object_or_404(ChatRoom, id=room_id, room_type='group')
 
        if not _is_admin(room, request.user):
            return Response(
                {"error": "Only group admins can add members."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        user_ids = request.data.get('user_ids', [])
        if not user_ids:
            return Response(
                {"error": "user_ids list is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
 
        added = []
        already_in = []
 
        for uid in user_ids:
            try:
                user = User.objects.get(id=uid, is_active=True)
                cp, created = ChatParticipant.objects.get_or_create(
                    room=room, user=user,
                    defaults={'role': 'member'}
                )
                if created:
                    added.append(user.full_name)
                else:
                    already_in.append(user.full_name)
            except User.DoesNotExist:
                continue
 
        return Response({
            "message": f"{len(added)} member(s) added.",
            "added": added,
            "already_in": already_in,
        })
 
 
# ── Remove Member ─────────────────────────────────────────────────────────────
 
class GroupRemoveMemberView(APIView):
    """
    DELETE /api/chat/rooms/<room_id>/members/<user_id>/remove/
    Admin can remove any member.
    A member cannot remove themselves here — use leave/ instead.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def delete(self, request, room_id, user_id):
        from .models import ChatRoom, ChatParticipant
        room = get_object_or_404(ChatRoom, id=room_id, room_type='group')
 
        if not _is_admin(room, request.user):
            return Response(
                {"error": "Only group admins can remove members."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        if str(request.user.id) == str(user_id):
            return Response(
                {"error": "Admins cannot remove themselves. Use /leave/ instead."},
                status=status.HTTP_400_BAD_REQUEST
            )
 
        target_cp = ChatParticipant.objects.filter(room=room, user_id=user_id).first()
        if not target_cp:
            return Response(
                {"error": "User is not in this group."},
                status=status.HTTP_404_NOT_FOUND
            )
 
        # Cannot remove another admin unless you are the room creator
        if target_cp.role == 'admin' and str(room.created_by_id) != str(request.user.id):
            return Response(
                {"error": "Only the group creator can remove other admins."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        target_cp.delete()
        return Response({"message": "Member removed from group."})
 
 
# ── Leave Group ───────────────────────────────────────────────────────────────
 
class LeaveGroupView(APIView):
    """
    POST /api/chat/rooms/<room_id>/leave/
    Any participant can leave the group.
    If the last admin leaves, the oldest member is promoted to admin.
    If no members remain, the room is deleted.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, room_id):
        from .models import ChatRoom, ChatParticipant
        room = get_object_or_404(
            ChatRoom, id=room_id, room_type='group',
            room_participants__user=request.user
        )
 
        cp = get_object_or_404(ChatParticipant, room=room, user=request.user)
        was_admin = cp.role == 'admin'
        cp.delete()
 
        remaining = ChatParticipant.objects.filter(room=room).order_by('joined_at')
 
        if not remaining.exists():
            room.delete()
            return Response({"message": "You left the group. Group deleted (no members left)."})
 
        # If the admin left and no other admin exists, promote oldest member
        if was_admin:
            admins_left = remaining.filter(role='admin').exists()
            if not admins_left:
                new_admin = remaining.first()
                new_admin.role = 'admin'
                new_admin.save(update_fields=['role'])
 
        return Response({"message": "You have left the group."})
 
 
# ── Update Group Info ─────────────────────────────────────────────────────────
 
class GroupUpdateView(APIView):
    """
    PATCH /api/chat/rooms/<room_id>/update/
    Body: { "name": "...", "description": "..." }
    Only group admins can update group info.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
 
    def patch(self, request, room_id):
        from .models import ChatRoom
        room = get_object_or_404(ChatRoom, id=room_id, room_type='group')
 
        if not _is_admin(room, request.user):
            return Response(
                {"error": "Only group admins can update group info."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        name = request.data.get('name', '').strip()
        description = request.data.get('description', '').strip()
        group_icon = request.FILES.get('group_icon')
 
        update_fields = []
        if name:
            room.name = name
            update_fields.append('name')
        if description is not None:
            room.description = description
            update_fields.append('description')
        if group_icon:
            room.group_icon = group_icon
            update_fields.append('group_icon')
 
        if update_fields:
            room.save(update_fields=update_fields)
 
        from .serializers import ChatRoomSerializer
        return Response(
            ChatRoomSerializer(room, context={'request': request}).data
        )
 
 
# ── Change Member Role (Promote/Demote) ───────────────────────────────────────
 
class GroupMemberRoleView(APIView):
    """
    PATCH /api/chat/rooms/<room_id>/members/<user_id>/role/
    Body: { "role": "admin" | "member" }
    Only group creator can promote/demote.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def patch(self, request, room_id, user_id):
        from .models import ChatRoom, ChatParticipant
        room = get_object_or_404(ChatRoom, id=room_id, room_type='group')
 
        # Only room creator can change roles
        if str(room.created_by_id) != str(request.user.id):
            return Response(
                {"error": "Only the group creator can change member roles."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        new_role = request.data.get('role', '').strip()
        if new_role not in ('admin', 'member'):
            return Response(
                {"error": "role must be 'admin' or 'member'."},
                status=status.HTTP_400_BAD_REQUEST
            )
 
        target = get_object_or_404(ChatParticipant, room=room, user_id=user_id)
        target.role = new_role
        target.save(update_fields=['role'])
 
        return Response({
            "message": f"Role updated to {new_role}.",
            "user_id": str(user_id),
            "role": new_role,
        })
 
 
# ── Invite Link ───────────────────────────────────────────────────────────────
 
class GroupInviteLinkView(APIView):
    """
    GET  /api/chat/rooms/<room_id>/invite-link/
         Admin gets or generates an invite link.
    POST /api/chat/rooms/join/<invite_code>/
         Anyone joins using the invite link.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, room_id):
        from .models import ChatRoom
        room = get_object_or_404(ChatRoom, id=room_id, room_type='group')
 
        if not _is_admin(room, request.user):
            return Response(
                {"error": "Only admins can generate invite links."},
                status=status.HTTP_403_FORBIDDEN
            )
 
        # Reuse or generate invite_code — store in room.description as hack
        # OR add invite_code field to ChatRoom in models.py (recommended).
        # Below uses description hack-free approach — store code in a simple KV.
        # For production: add `invite_code = models.CharField(...)` to ChatRoom.
        # Here we derive a stable code from room id (simpler, no migration needed):
        code = str(room.id).replace('-', '')[:16]
 
        base_url = request.build_absolute_uri('/').rstrip('/')
        link = f"{base_url}/api/chat/rooms/join/{code}/"
        return Response({
            "invite_code": code,
            "invite_link": link,
            "group_name": room.name,
        })
 
 
class JoinGroupViaInviteView(APIView):
    """
    POST /api/chat/rooms/join/<invite_code>/
    Join a group using invite code.
    """
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, invite_code):
        from .models import ChatRoom, ChatParticipant
 
        # Match the first 16 chars of room UUID without dashes
        rooms = ChatRoom.objects.filter(room_type='group')
        room = None
        for r in rooms:
            code = str(r.id).replace('-', '')[:16]
            if code == invite_code:
                room = r
                break
 
        if not room:
            return Response(
                {"error": "Invalid invite link or group not found."},
                status=status.HTTP_404_NOT_FOUND
            )
 
        cp, created = ChatParticipant.objects.get_or_create(
            room=room, user=request.user,
            defaults={'role': 'member'}
        )
 
        if not created:
            return Response({
                "message": "You are already in this group.",
                "room_id": str(room.id),
                "already_member": True,
            })
 
        from .serializers import ChatRoomSerializer
        return Response({
            "message": f"You joined '{room.name}'!",
            "room_id": str(room.id),
            "already_member": False,
            "room": ChatRoomSerializer(room, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

# ══════════════════════════════════════════════════════════════════════════════
# STORIES
# ══════════════════════════════════════════════════════════════════════════════

class StoryPresignView(APIView):
    """
    POST /api/stories/presign/
    Body: { "file_name": "story.jpg", "mime_type": "image/jpeg" }
    Response: { "upload_url": "...", "file_url": "..." }
    R2 presigned URL for direct story media upload from Flutter.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        file_name = request.data.get('file_name', '').strip()
        mime_type = request.data.get('mime_type', 'image/jpeg').strip()

        if not file_name:
            return Response({'error': 'file_name required.'}, status=status.HTTP_400_BAD_REQUEST)

        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else 'jpg'
        key = f"stories/{request.user.id}/{_uuid.uuid4()}.{ext}"

        try:
            r2 = boto3.client(
                's3',
                endpoint_url=settings.R2_ENDPOINT_URL,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=BotoConfig(signature_version='s3v4'),
                region_name='auto',
            )
            upload_url = r2.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.R2_BUCKET_NAME,
                    'Key': key,
                    'ContentType': mime_type,
                },
                ExpiresIn=600,  # 10 min
            )
            file_url = f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"
            return Response({'upload_url': upload_url, 'file_url': file_url})
        except Exception as e:
            logger.error(f"Story presign error: {e}")
            return Response({'error': 'Could not generate upload URL.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StoryListCreateView(APIView):
    """
    GET  /api/stories/         — Apni + connections ki active stories
    POST /api/stories/         — Nayi story create karo (after R2 upload)
    Body: { "media_url": "...", "media_type": "image", "caption": "..." }
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import Story
        # Apni stories + connections ki stories (active only)
        now = timezone.now()
        connected_ids = list(
            Connection.objects.filter(
                Q(sender=request.user) | Q(receiver=request.user),
                status='accepted'
            ).values_list(
                'receiver_id', flat=True
            )
        ) + list(
            Connection.objects.filter(
                Q(sender=request.user) | Q(receiver=request.user),
                status='accepted'
            ).values_list(
                'sender_id', flat=True
            )
        )

        # Chat participants bhi include karo —
        # Jo log sirf chat room mein hain (connection nahi hai) unki stories bhi dikhao
        chat_room_ids = ChatParticipant.objects.filter(
            user=request.user
        ).values_list('room_id', flat=True)

        chat_participant_ids = list(
            ChatParticipant.objects.filter(
                room_id__in=chat_room_ids
            ).exclude(
                user=request.user
            ).values_list('user_id', flat=True)
        )

        # Apna ID bhi include karo
        all_ids = list(set(connected_ids + chat_participant_ids + [request.user.id]))

        stories = (
            Story.objects
            .filter(author_id__in=all_ids, expires_at__gt=now)
            .select_related('author')
            .prefetch_related('seen_by')
            .order_by('-created_at')
        )

        # Group by author
        from collections import defaultdict
        grouped = defaultdict(list)
        for s in stories:
            grouped[s.author_id].append(s)

        result = []
        for author_id, author_stories in grouped.items():
            first = author_stories[0]
            author = first.author
            has_unseen = any(request.user not in s.seen_by.all() for s in author_stories)
            result.append({
                'author_id':    str(author.id),
                'author_name':  author.full_name,
                'author_photo': getattr(author, 'advocate_profile', None) and
                                author.advocate_profile.profile_photo or None,
                'is_own':       author.id == request.user.id,
                'has_unseen':   has_unseen,
                'stories': [
                    {
                        'id':         str(s.id),
                        'media_url':  s.media_url,
                        'media_type': s.media_type,
                        'caption':    s.caption,
                        'seen':       request.user in s.seen_by.all(),
                        'seen_count': s.seen_by.count(),
                        'created_at': s.created_at.isoformat(),
                        'expires_at': s.expires_at.isoformat(),
                    }
                    for s in author_stories
                ],
            })

        return Response(result)

    def post(self, request):
        from .models import Story
        media_url  = request.data.get('media_url', '').strip()
        media_type = request.data.get('media_type', 'image').strip()
        caption    = request.data.get('caption', '').strip()

        if not media_url:
            return Response({'error': 'media_url required.'}, status=status.HTTP_400_BAD_REQUEST)
        if media_type not in ('image', 'video'):
            return Response({'error': 'media_type must be image or video.'}, status=status.HTTP_400_BAD_REQUEST)

        story = Story.objects.create(
            author=request.user,
            media_url=media_url,
            media_type=media_type,
            caption=caption,
        )
        return Response({
            'id':         str(story.id),
            'media_url':  story.media_url,
            'media_type': story.media_type,
            'caption':    story.caption,
            'expires_at': story.expires_at.isoformat(),
            'created_at': story.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class StoryMarkSeenView(APIView):
    """
    POST /api/stories/<story_id>/seen/
    Story ko seen mark karo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, story_id):
        from .models import Story
        story = get_object_or_404(Story, id=story_id, expires_at__gt=timezone.now())
        story.seen_by.add(request.user)
        return Response({'message': 'Marked as seen.'})


class StoryDeleteView(APIView):
    """
    DELETE /api/stories/<story_id>/
    Apni story delete karo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, story_id):
        from .models import Story
        story = get_object_or_404(Story, id=story_id, author=request.user)
        story.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ══════════════════════════════════════════════════════════════════════════════
# ONE-TIME FIX: Existing Users ke liye AdvocateProfile create karo
# GET /api/admin/fix-profiles/
# ══════════════════════════════════════════════════════════════════════════════

class FixMissingAdvocateProfilesView(APIView):
    """
    GET /api/admin/fix-profiles/
    Sab active users jinka AdvocateProfile nahi bana, unka profile create karo.
    Yeh one-time fix hai existing 36 users ke liye.
    Only staff/superuser call kar sakta hai.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        users_without_profile = User.objects.filter(
            is_active=True
        ).exclude(
            id__in=AdvocateProfile.objects.values_list('user_id', flat=True)
        )
        created_count = 0
        created_for = []
        for user in users_without_profile:
            AdvocateProfile.objects.create(user=user)
            created_count += 1
            created_for.append(user.username)

        return Response({
            'message': f'{created_count} profiles created.',
            'created_for': created_for,
        })