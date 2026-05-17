"""
Advocate App — Views (Flutter-aligned)
Every URL, field name, and response key matches the Flutter service files exactly.
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
    Channel, ChannelMembership, ChannelPost, ChannelPostComment, ChannelPostLike,
    Post, PostReaction, PostComment,
    CaseGroup, GroupMembership, GroupDocument,
    Notification, Report,
)
from .serializers import (
    RegisterSerializer, LoginSerializer, OTPVerifySerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, ChangePasswordSerializer,
    UserProfileSerializer, AdminUserSerializer, AdminAdvocateVerifySerializer,
    AdvocateProfileSerializer, AdvocateVerificationSerializer,
    AdvocateEducationSerializer, AdvocateExperienceSerializer, AdvocateAchievementSerializer,
    ConnectionSerializer, ConnectionRequestSerializer, FollowSerializer,
    ChatRoomSerializer, MessageSerializer, CreateDirectChatSerializer, CreateGroupChatSerializer,
    ChannelSerializer, ChannelPostSerializer, ChannelPostCommentSerializer,
    PostSerializer, PostCommentSerializer,
    CaseGroupSerializer, GroupDocumentSerializer,
    NotificationSerializer, ReportSerializer,
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

class HealthView(APIView):
    """
    Lightweight Health Check - Neon CU bachane ke liye
    Database check completely removed.
    Sirf yeh check karega ki Django app chal raha hai.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "status": "ok",
            "timestamp": timezone.now().isoformat(),
            "checks": {
                "database": "skipped",   # ← Ab check nahi hoga
                "api": "ok"
            },
            "message": "API is running (Database check disabled to save Neon CU)",
            "version": "1.0.0",
        }, status=200)
        
# ══════════════════════════════════════════════════════════════════════════════
# AUTH VIEWS
# ══════════════════════════════════════════════════════════════════════════════

# lib/views.py  →  Replace your RegisterView with this:

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        
        # Ensure password2 is present for serializer validation
        if 'password2' not in data:
            data['password2'] = data.get('password', '')

        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
            print("🔴 Registration Validation Error:", serializer.errors)  # ← For debugging
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()

        # Auto verify user (since we removed OTP)
        user.is_verified = True
        user.save(update_fields=['is_verified'])

        return Response({
            "message": "Account created successfully!",
            "user_id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_verified": True,
        }, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/
    Flutter sends: username, password
    Returns: { access, refresh, user: {...} }
    """
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            username = request.data.get('username', '').lower()
            try:
                user = User.objects.get(username=username)
                response.data['user'] = {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email or '',
                    'full_name': user.full_name,
                    'is_verified': user.is_verified,
                    'is_advocate': user.is_advocate,
                    'advocate_status': user.advocate_status,
                    'is_online': user.is_online,
                }
            except User.DoesNotExist:
                pass
        return response


class LogoutView(APIView):
    """POST /api/auth/logout/  — Flutter sends: refresh_token"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh_token"))
            token.blacklist()
        except Exception:
            pass
        return Response({"message": "Logged out successfully."})


class VerifyOTPView(APIView):
    """POST /api/auth/verify-otp/  — Flutter sends: email, code, purpose"""
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
    """POST /api/auth/resend-otp/  — Flutter sends: email, purpose"""
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
    """POST /api/auth/forgot-password/  — Flutter sends: email"""
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
    """
    POST /api/auth/reset-password/
    Flutter sends: email, code, new_password   (note: 'code' not 'otp_code')
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email        = request.data.get('email', '')
        code         = request.data.get('code', '')          # Flutter field name
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
    """POST /api/auth/change-password/  — Flutter sends: old_password, new_password"""
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
    """POST /api/auth/delete-account/  — Flutter sends: password"""
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


# ══════════════════════════════════════════════════════════════════════════════
# ADVOCATE PROFILE VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class AdvocateProfileListView(generics.ListAPIView):
    """
    GET /api/advocates/
    profile_service.searchAdvocates() — query params:
    name, city, state, practice_area, court, language, min_experience, max_experience, page
    """
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = AdvocateProfileFilter
    search_fields = ['user__full_name', 'bio', 'city', 'state']
    ordering_fields = ['years_of_experience', 'connection_count', 'follower_count']
    ordering = ['-connection_count']

    def get_queryset(self):
        return AdvocateProfile.objects.filter(
            user__is_active=True,
            user__advocate_status='approved',
            is_public=True,
        ).select_related('user').prefetch_related('education', 'experience', 'achievements')


class MyAdvocateProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/advocates/me/"""
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return profile


class AdvocateProfileDetailView(generics.RetrieveAPIView):
    """GET /api/advocates/<user_id>/"""
    serializer_class = AdvocateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Pehle User fetch karo — agar user hi nahi toh 404 sahi hai
        user = get_object_or_404(User, id=self.kwargs['user_id'], is_active=True)
        # Profile ensure karo — get_or_create se 404 kabhi nahi aayega
        # (signal se toh ban hi jaata hai, yeh double safety hai)
        profile, _ = AdvocateProfile.objects.get_or_create(user=user)
        return profile


class AdvocateVerificationView(APIView):
    """
    POST /api/advocates/verify/
    Flutter sends: bar_council_id (text), document (file)
    """
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
    """CRUD /api/advocates/education/"""
    serializer_class   = AdvocateEducationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateEducation.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


class AdvocateExperienceViewSet(viewsets.ModelViewSet):
    """CRUD /api/advocates/experience/"""
    serializer_class   = AdvocateExperienceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateExperience.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


class AdvocateAchievementViewSet(viewsets.ModelViewSet):
    """CRUD /api/advocates/achievements/"""
    serializer_class   = AdvocateAchievementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        return AdvocateAchievement.objects.filter(profile=profile)

    def perform_create(self, serializer):
        profile, _ = AdvocateProfile.objects.get_or_create(user=self.request.user)
        serializer.save(profile=profile)


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTIONS  —  profile_service.dart
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionListView(generics.ListAPIView):
    """
    GET /api/connections/
    profile_service.getConnections() — returns accepted connections
    Also handles ?status=pending&direction=sent (getSentConnections)
    """
    serializer_class   = ConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs_status = self.request.query_params.get('status')
        direction = self.request.query_params.get('direction')

        if qs_status == 'pending' and direction == 'sent':
            return Connection.objects.filter(
                sender=self.request.user, status='pending'
            ).select_related('sender', 'receiver')

        return Connection.objects.filter(
            Q(sender=self.request.user) | Q(receiver=self.request.user),
            status='accepted'
        ).select_related('sender', 'receiver')


class PendingConnectionsView(generics.ListAPIView):
    """GET /api/connections/pending/  — profile_service.getPendingConnections()"""
    serializer_class   = ConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Connection.objects.filter(
            receiver=self.request.user, status='pending'
        ).select_related('sender', 'receiver')


class SendConnectionRequestView(APIView):
    """
    POST /api/connections/send/
    Flutter profile_service.sendConnectionRequest() sends:
      receiver_id (not 'receiver'), optional message
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Flutter sends receiver_id — map to our model field
        receiver_id = request.data.get('receiver_id') or request.data.get('receiver')
        message     = request.data.get('message', '')

        if not receiver_id:
            return Response({"error": "receiver_id is required."}, status=400)

        receiver = get_object_or_404(User, id=receiver_id, is_active=True)

        if receiver == request.user:
            return Response({"error": "You cannot connect with yourself."}, status=400)

        existing = Connection.objects.filter(
            Q(sender=request.user, receiver=receiver) |
            Q(sender=receiver, receiver=request.user)
        ).first()

        if existing:
            return Response({"error": f"Connection already exists: {existing.status}"}, status=400)

        conn = Connection.objects.create(sender=request.user, receiver=receiver, message=message)

        create_notification(
            recipient=receiver,
            notif_type='connection_request',
            title='New Connection Request',
            body=f"{request.user.full_name} sent you a connection request.",
            sender=request.user,
            data={'connection_id': str(conn.id)},
        )
        try:
            send_connection_request_email(request.user, receiver)
        except Exception:
            pass

        return Response({"message": "Connection request sent.", "id": str(conn.id)}, status=201)


class ConnectionDetailView(APIView):
    """
    PATCH /api/connections/<id>/   — respondToConnection (status: accepted/rejected)
    DELETE /api/connections/<id>/  — removeConnection
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        new_status = request.data.get('status', '')
        connection = get_object_or_404(Connection, id=pk)

        # Only receiver can accept/reject; sender can withdraw
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
    """
    POST   /api/follow/<user_id>/  — followUser
    DELETE /api/follow/<user_id>/  — unfollowUser
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = get_object_or_404(User, id=user_id, is_active=True)
        if target == request.user:
            return Response({"error": "Cannot follow yourself."}, status=400)

        _, created = Follow.objects.get_or_create(follower=request.user, following=target)
        if not created:
            return Response({"error": "Already following."}, status=400)

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
        return Response({"message": f"Now following {target.full_name}."}, status=201)

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
    """GET /api/network/suggested/"""
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
# CHAT / MESSAGING  —  chat_service.dart
# ══════════════════════════════════════════════════════════════════════════════

class ChatRoomListView(generics.ListAPIView):
    """GET /api/chat/rooms/"""
    serializer_class   = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChatRoom.objects.filter(
            room_participants__user=self.request.user
        ).prefetch_related('room_participants__user', 'messages').distinct().order_by('-updated_at')


class CreateDirectChatView(APIView):
    """
    POST /api/chat/rooms/direct/
    Flutter: getOrCreateDirect(userId) sends { user_id: userId }
    """
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
    """
    POST /api/chat/rooms/group/
    Flutter: createGroup() sends { name, participant_ids: [...] }
    """
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
    """
    GET  /api/chat/rooms/<room_id>/messages/  — getMessages
    POST /api/chat/rooms/<room_id>/messages/  — sendFileMessage (multipart)
    """
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

        # Update last_read
        ChatParticipant.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())

        return Response({
            "count": total,
            "results": MessageSerializer(messages, many=True, context={'request': request}).data,
        })

    def post(self, request, room_id):
        """sendFileMessage — multipart: message_type + file"""
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
    """
    PATCH  /api/chat/messages/<id>/  — editMessage sends { content }
    DELETE /api/chat/messages/<id>/  — deleteMessage
    """
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
    """POST /api/chat/rooms/<room_id>/read/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id, room_participants__user=request.user)
        for msg in Message.objects.filter(room=room, is_deleted=False).exclude(sender=request.user):
            MessageReadReceipt.objects.get_or_create(message=msg, user=request.user)
        ChatParticipant.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        return Response({"message": "Messages marked as read."})


# ══════════════════════════════════════════════════════════════════════════════
# CHANNELS  —  channel_service.dart
# ══════════════════════════════════════════════════════════════════════════════

class ChannelListView(generics.ListAPIView):
    """
    GET /api/channels/
    channel_service.getChannels() — query: channel_type, city, state, is_official
    """
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class    = ChannelFilter
    search_fields      = ['name', 'description', 'court_name', 'city', 'state']
    ordering_fields    = ['member_count', 'created_at']
    ordering           = ['-member_count']

    def get_queryset(self):
        return Channel.objects.filter(is_private=False)


class MyChannelsView(generics.ListAPIView):
    """GET /api/channels/mine/"""
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Channel.objects.filter(memberships__user=self.request.user)


class ChannelDetailView(generics.RetrieveAPIView):
    """GET /api/channels/<id>/"""
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset           = Channel.objects.all()
    lookup_field       = 'id'


class CreateChannelView(generics.CreateAPIView):
    """POST /api/channels/create/"""
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
    """POST /api/channels/<pk>/join/"""
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
    """DELETE /api/channels/<pk>/leave/"""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        channel = get_object_or_404(Channel, id=pk)
        deleted, _ = ChannelMembership.objects.filter(channel=channel, user=request.user).delete()
        if deleted:
            channel.member_count = max(0, channel.member_count - 1)
            channel.save(update_fields=['member_count'])
        return Response(status=204)


class ChannelPostListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/channels/<channel_id>/posts/  — getChannelPosts
    POST /api/channels/<channel_id>/posts/  — createChannelPost
    Flutter POST sends: content (text) + optional attachment (file)
    """
    serializer_class   = ChannelPostSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        channel = get_object_or_404(Channel, id=self.kwargs['channel_id'])
        return ChannelPost.objects.filter(channel=channel).select_related('author')

    def perform_create(self, serializer):
        channel = get_object_or_404(
            Channel, id=self.kwargs['channel_id'],
            memberships__user=self.request.user,
        )
        attachment = self.request.FILES.get('attachment')
        att_type   = ''
        if attachment:
            att_type = get_file_type(attachment)
        serializer.save(author=self.request.user, channel=channel,
                        attachment=attachment, attachment_type=att_type)


class ChannelPostLikeView(APIView):
    """POST /api/channels/posts/<pk>/like/  — likeChannelPost (toggle)"""
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
    """
    GET/POST /api/channels/posts/<post_id>/comments/
    Flutter: addChannelComment sends: content, optional parent (parentId)
    """
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
# COMMUNITY FEED  —  post_service.dart
# Flutter uses /feed/ for everything (get, create, delete, react, comments)
# ══════════════════════════════════════════════════════════════════════════════

class FeedListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/feed/  — getFeed (post_type filter, page)
    POST /api/feed/  — createPost (content, post_type, media file, is_public)
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
            ids.add(s); ids.add(r)
        ids.add(self.request.user.id)

        return Post.objects.filter(
            Q(author_id__in=ids) | Q(is_public=True)
        ).select_related('author').distinct().order_by('-created_at')

    def perform_create(self, serializer):
        file       = self.request.FILES.get('media')
        media_type = get_file_type(file) if file else ''
        serializer.save(author=self.request.user, media=file, media_type=media_type)


class PostDetailView(APIView):
    """
    DELETE /api/feed/<pk>/   — deletePost
    GET    /api/feed/<pk>/   — single post
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        post = get_object_or_404(Post, id=pk)
        return Response(PostSerializer(post, context={'request': request}).data)

    def delete(self, request, pk):
        post = get_object_or_404(Post, id=pk, author=request.user)
        post.delete()
        return Response(status=204)


class PostReactView(APIView):
    """
    POST   /api/feed/<pk>/react/  — reactToPost sends { reaction_type }
    DELETE /api/feed/<pk>/react/  — removeReaction
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        post          = get_object_or_404(Post, id=pk)
        reaction_type = request.data.get('reaction_type', 'like')

        existing = PostReaction.objects.filter(post=post, user=request.user).first()
        if existing:
            if existing.reaction_type == reaction_type:
                # Same reaction → toggle off
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
    """
    GET  /api/feed/<post_id>/comments/  — getComments
    POST /api/feed/<post_id>/comments/  — addComment sends: content, optional parent (parentId)
    """
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


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS  —  notification_service.dart
# ══════════════════════════════════════════════════════════════════════════════

class NotificationListView(generics.ListAPIView):
    """GET /api/notifications/  — getNotifications (page)"""
    serializer_class   = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related('sender').order_by('-created_at')


class UnreadNotificationCountView(APIView):
    """GET /api/notifications/unread-count/  — getUnreadCount → { unread_count }"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread_count": count})


class MarkNotificationReadView(APIView):
    """POST /api/notifications/<pk>/read/  — markRead"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        notif = get_object_or_404(Notification, id=pk, recipient=request.user)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response({"message": "Marked as read."})


class MarkAllNotificationsReadView(APIView):
    """POST /api/notifications/read-all/  — markAllRead"""
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
            "advocates_total":    User.objects.filter(is_advocate=True).count(),
            "advocates_pending":  User.objects.filter(advocate_status='pending').count(),
            "advocates_approved": User.objects.filter(advocate_status='approved').count(),
            "total_posts":        Post.objects.count(),
            "total_channels":     Channel.objects.count(),
            "total_messages":     Message.objects.count(),
            "new_users_30d":      User.objects.filter(date_joined__gte=last30).count(),
            "new_posts_30d":      Post.objects.filter(created_at__gte=last30).count(),
            "pending_reports":    Report.objects.filter(status='pending').count(),
        })


class AdminChannelListView(generics.ListAPIView):
    serializer_class   = ChannelSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset           = Channel.objects.all().order_by('-created_at')