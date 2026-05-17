"""
Utility functions: OTP generation, email sending, etc.
"""
import random
import string
import logging
from datetime import timedelta

from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model

from .models import OTP

logger = logging.getLogger(__name__)
User = get_user_model()


# ─── OTP ──────────────────────────────────────────────────────────────────────

def generate_otp(length=6):
    """Generate a numeric OTP code."""
    return ''.join(random.choices(string.digits, k=length))


def create_otp(user, purpose):
    """
    Invalidate old OTPs for same purpose, then create a new one.
    Returns the OTP instance.
    """
    # Expire all previous OTPs for this user+purpose
    OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

    code = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)

    otp = OTP.objects.create(
        user=user,
        code=code,
        purpose=purpose,
        expires_at=expires_at,
    )
    return otp


def verify_otp(user, code, purpose):
    """
    Returns (True, None) if valid, (False, error_message) otherwise.
    Marks OTP as used on success.
    """
    otp = OTP.objects.filter(
        user=user,
        code=code,
        purpose=purpose,
        is_used=False,
    ).order_by('-created_at').first()

    if not otp:
        return False, "Invalid OTP. Please request a new one."

    if not otp.is_valid():
        return False, f"OTP has expired. Please request a new one."

    otp.is_used = True
    otp.save(update_fields=['is_used'])
    return True, None


# ─── Email Helpers ────────────────────────────────────────────────────────────

def send_otp_email(user, otp_code, purpose):
    """Send OTP email based on purpose."""
    subjects = {
        'email_verify': 'Verify your AdvocateApp account',
        'forgot_password': 'Reset your AdvocateApp password',
        'phone_verify': 'Phone verification – AdvocateApp',
    }
    messages = {
        'email_verify': (
            f"Hello {user.full_name},\n\n"
            f"Your email verification OTP is: {otp_code}\n\n"
            f"This OTP is valid for {settings.OTP_EXPIRY_MINUTES} minutes.\n"
            f"If you did not request this, please ignore this email.\n\n"
            f"– AdvocateApp Team"
        ),
        'forgot_password': (
            f"Hello {user.full_name},\n\n"
            f"Your password reset OTP is: {otp_code}\n\n"
            f"This OTP is valid for {settings.OTP_EXPIRY_MINUTES} minutes.\n"
            f"If you did not request this, please ignore this email.\n\n"
            f"– AdvocateApp Team"
        ),
        'phone_verify': (
            f"Hello {user.full_name},\n\n"
            f"Your phone verification OTP is: {otp_code}\n\n"
            f"This OTP is valid for {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
            f"– AdvocateApp Team"
        ),
    }

    subject = subjects.get(purpose, 'AdvocateApp OTP')
    message = messages.get(purpose, f"Your OTP is: {otp_code}")

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info(f"OTP email sent to {user.email} for purpose: {purpose}")
    except Exception as e:
        logger.error(f"Failed to send OTP email to {user.email}: {e}")
        raise


def send_verification_status_email(user, status, admin_notes=''):
    """Notify advocate about their verification result."""
    if status == 'approved':
        subject = "🎉 Your Advocate profile has been verified!"
        message = (
            f"Congratulations {user.full_name}!\n\n"
            f"Your advocate profile has been successfully verified. "
            f"You now have the Verified Advocate badge on your profile.\n\n"
            f"You can now access all advocate features on AdvocateApp.\n\n"
            f"– AdvocateApp Team"
        )
    else:
        subject = "Update on your Advocate Verification"
        message = (
            f"Hello {user.full_name},\n\n"
            f"Unfortunately, your advocate verification could not be approved at this time.\n\n"
            f"Reason: {admin_notes or 'Please contact support for more information.'}\n\n"
            f"You can re-apply with correct documents. If you believe this is an error, "
            f"please contact our support team.\n\n"
            f"– AdvocateApp Team"
        )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Failed to send verification email to {user.email}: {e}")


def send_connection_request_email(sender, receiver):
    """Email notification for connection request."""
    try:
        send_mail(
            subject=f"{sender.full_name} wants to connect with you on AdvocateApp",
            message=(
                f"Hello {receiver.full_name},\n\n"
                f"{sender.full_name} has sent you a connection request on AdvocateApp.\n\n"
                f"Log in to accept or decline the request.\n\n"
                f"– AdvocateApp Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[receiver.email],
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Failed to send connection email: {e}")


# ─── Notification Helpers ─────────────────────────────────────────────────────

def create_notification(recipient, notif_type, title, body, sender=None, data=None):
    """Create a Notification record and optionally push via WebSocket."""
    from .models import Notification
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    notif = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notif_type=notif_type,
        title=title,
        body=body,
        data=data or {},
    )

    # Push real-time notification via WebSocket
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"notifications_{recipient.id}",
            {
                "type": "send_notification",
                "notification": {
                    "id": str(notif.id),
                    "type": notif_type,
                    "title": title,
                    "body": body,
                    "data": data or {},
                    "created_at": notif.created_at.isoformat(),
                }
            }
        )
    except Exception as e:
        logger.warning(f"WebSocket push failed for notification: {e}")

    return notif


# ─── File Helpers ─────────────────────────────────────────────────────────────

def get_file_type(file):
    """Determine file type from extension."""
    if not file:
        return 'unknown'
    name = file.name.lower()
    if name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
        return 'image'
    elif name.endswith('.pdf'):
        return 'pdf'
    elif name.endswith(('.doc', '.docx')):
        return 'doc'
    elif name.endswith(('.mp3', '.m4a', '.ogg', '.wav')):
        return 'voice'
    return 'other'


def get_direct_room(user1, user2):
    """Get or create a direct message room between two users."""
    from .models import ChatRoom, ChatParticipant

    # Find existing direct room with exactly these two participants
    rooms = ChatRoom.objects.filter(
        room_type='direct',
        room_participants__user=user1
    ).filter(
        room_participants__user=user2
    )

    if rooms.exists():
        return rooms.first(), False

    # Create new room
    room = ChatRoom.objects.create(room_type='direct', created_by=user1)
    ChatParticipant.objects.create(room=room, user=user1)
    ChatParticipant.objects.create(room=room, user=user2)
    return room, True