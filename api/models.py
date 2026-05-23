"""
Advocate Networking App - All Models
UI Features aligned with LegalConnect screenshots:
- Home: Stats (Cases, Connections, Hearings, Rating), Today's Hearings, Recent Updates
- Channels: Sub-channels, pinned posts, announcement support
- Chat: Pinned chats, All/Direct/Groups/Pinned tabs, unread badges
- Feed: Hashtags, trending topics, save/share, people to follow
- Profile: Online/Away/Offline status, theme/accent preferences, privacy settings
"""
import uuid
import pyotp
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField


# ══════════════════════════════════════════════════════════════════════════════
# USER & AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        if "email" in extra_fields:
            extra_fields["email"] = self.normalize_email(extra_fields["email"])
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_verified", True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ADVOCATE_STATUS = [
        ('none', 'Not an Advocate'),
        ('pending', 'Verification Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # Online presence status — Profile screen mein Online/Away/Offline toggle
    PRESENCE_STATUS = [
        ('online', 'Online'),
        ('away', 'Away'),
        ('offline', 'Offline'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=50, unique=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    phone = PhoneNumberField(blank=True, null=True, unique=True)
    full_name = models.CharField(max_length=150)

    # Flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    is_advocate = models.BooleanField(default=False)
    advocate_status = models.CharField(max_length=20, choices=ADVOCATE_STATUS, default='none')

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True)

    # Online presence — Profile screen: Online/Away/Offline
    is_online = models.BooleanField(default=False)
    presence_status = models.CharField(max_length=10, choices=PRESENCE_STATUS, default='offline')

    # ── Profile screen: Appearance settings ──────────────────────────────────
    theme = models.CharField(max_length=10, default='dark',
                             choices=[('dark', 'Dark'), ('light', 'Light')])
    accent_color = models.CharField(max_length=20, default='blue')  # e.g. 'blue','green','red'

    # ── Profile screen: Notification toggles ─────────────────────────────────
    notif_messages = models.BooleanField(default=True)
    notif_group_mentions = models.BooleanField(default=True)
    notif_stories = models.BooleanField(default=False)
    notif_calls = models.BooleanField(default=True)

    # ── Profile screen: Privacy settings ─────────────────────────────────────
    privacy_read_receipts = models.BooleanField(default=True)   # Let others see read receipts
    privacy_last_seen = models.BooleanField(default=True)        # Show last seen
    privacy_online_status = models.BooleanField(default=True)    # Show online status

    # ── Home screen: Advocate Rating (from profile stats) ────────────────────
    advocate_rating = models.DecimalField(max_digits=3, decimal_places=1, default=0.0)
    cases_handled = models.PositiveIntegerField(default=0)       # Home stats card

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'full_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def is_advocate_verified(self):
        return self.is_advocate and self.advocate_status == 'approved'


class OTP(models.Model):
    PURPOSE_CHOICES = [
        ('email_verify', 'Email Verification'),
        ('forgot_password', 'Forgot Password'),
        ('phone_verify', 'Phone Verification'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'otps'
        ordering = ['-created_at']

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def __str__(self):
        return f"OTP({self.purpose}) for {self.user.email}"


# ══════════════════════════════════════════════════════════════════════════════
# ADVOCATE PROFESSIONAL PROFILE
# ══════════════════════════════════════════════════════════════════════════════

PRACTICE_AREAS = [
    ('criminal', 'Criminal Law'),
    ('civil', 'Civil Law'),
    ('corporate', 'Corporate Law'),
    ('family', 'Family Law'),
    ('constitutional', 'Constitutional Law'),
    ('tax', 'Tax Law'),
    ('property', 'Property Law'),
    ('intellectual_property', 'Intellectual Property'),
    ('labour', 'Labour Law'),
    ('environmental', 'Environmental Law'),
    ('cyber', 'Cyber Law'),
    ('banking', 'Banking & Finance Law'),
    ('consumer', 'Consumer Law'),
    ('immigration', 'Immigration Law'),
    ('arbitration', 'Arbitration & Mediation'),
    ('other', 'Other'),
]

COURTS = [
    ('supreme_court', 'Supreme Court of India'),
    ('high_court', 'High Court'),
    ('district_court', 'District Court'),
    ('family_court', 'Family Court'),
    ('consumer_court', 'Consumer Court'),
    ('tribunal', 'Tribunal'),
    ('sessions_court', 'Sessions Court'),
    ('magistrate_court', 'Magistrate Court'),
    ('civil_court', 'Civil Court'),
    ('revenue_court', 'Revenue Court'),
]


class AdvocateProfile(models.Model):
    """Extended professional profile for verified advocates."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='advocate_profile')

    # Verification
    bar_council_id = models.CharField(max_length=100, unique=True, null=True, blank=True, default=None)
    bar_council_id_image = models.ImageField(upload_to='bar_council_ids/', blank=True)
    enrollment_number = models.CharField(max_length=100, blank=True)
    enrollment_year = models.PositiveIntegerField(null=True, blank=True)
    state_bar_council = models.CharField(max_length=100, blank=True)

    # Profile
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    cover_photo = models.ImageField(upload_to='cover_photos/', blank=True, null=True)
    bio = models.TextField(max_length=2000, blank=True)
    tagline = models.CharField(max_length=200, blank=True)

    # Professional
    years_of_experience = models.PositiveIntegerField(default=0)
    specializations = models.JSONField(default=list, blank=True)
    courts_practiced = models.JSONField(default=list, blank=True)
    # Primary court — onboarding step 1 mein select hota hai
    primary_court = models.CharField(max_length=50, blank=True,
                                     choices=COURTS, default='')
    languages_known = models.JSONField(default=list, blank=True)

    # Location
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    office_address = models.TextField(blank=True)
    pincode = models.CharField(max_length=10, blank=True)

    # Contact (public)
    public_email = models.EmailField(blank=True)
    public_phone = PhoneNumberField(blank=True, null=True)
    website = models.URLField(blank=True)
    linkedin = models.URLField(blank=True)

    # Privacy
    is_public = models.BooleanField(default=True)
    show_contact = models.BooleanField(default=True)

    # Onboarding — pehli baar login ke baad profile setup complete hua ya nahi
    onboarding_complete = models.BooleanField(default=False)

    # Stats (cached) — Home screen stats cards + Profile screen
    connection_count = models.PositiveIntegerField(default=0)
    follower_count = models.PositiveIntegerField(default=0)
    post_count = models.PositiveIntegerField(default=0)
    media_count = models.PositiveIntegerField(default=0)    # Profile: 48 Media
    group_count = models.PositiveIntegerField(default=0)    # Profile: 6 Groups
    message_count = models.PositiveIntegerField(default=0)  # Profile: 2.4k Messages

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'advocate_profiles'

    def __str__(self):
        return f"Profile: {self.user.full_name}"


class AdvocateEducation(models.Model):
    profile = models.ForeignKey(AdvocateProfile, on_delete=models.CASCADE, related_name='education')
    institution = models.CharField(max_length=200)
    degree = models.CharField(max_length=200)
    field_of_study = models.CharField(max_length=200, blank=True)
    start_year = models.PositiveIntegerField()
    end_year = models.PositiveIntegerField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'advocate_education'
        ordering = ['-end_year', '-start_year']


class AdvocateExperience(models.Model):
    profile = models.ForeignKey(AdvocateProfile, on_delete=models.CASCADE, related_name='experience')
    title = models.CharField(max_length=200)
    firm_or_court = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'advocate_experience'
        ordering = ['-start_date']


class AdvocateAchievement(models.Model):
    profile = models.ForeignKey(AdvocateProfile, on_delete=models.CASCADE, related_name='achievements')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    issuing_organization = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'advocate_achievements'


# ══════════════════════════════════════════════════════════════════════════════
# HOME SCREEN — Today's Hearings & Recent Updates
# ══════════════════════════════════════════════════════════════════════════════

class Hearing(models.Model):
    """
    Home screen: TODAY'S HEARINGS section.
    e.g. 10:30 - Sharma vs State of Delhi - Delhi HC · Court Room 4
    """
    HEARING_TYPES = [
        ('physical', 'Physical'),
        ('virtual', 'Virtual'),
        ('hybrid', 'Hybrid'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    advocate = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hearings')
    case_title = models.CharField(max_length=300)        # "Sharma vs State of Delhi"
    case_number = models.CharField(max_length=100, blank=True)
    court = models.CharField(max_length=200)             # "Delhi HC"
    court_room = models.CharField(max_length=100, blank=True)  # "Court Room 4"
    hearing_time = models.TimeField()                    # 10:30
    hearing_date = models.DateField()
    hearing_type = models.CharField(max_length=10, choices=HEARING_TYPES, default='physical')
    notes = models.TextField(blank=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hearings'
        ordering = ['hearing_date', 'hearing_time']

    def __str__(self):
        return f"{self.case_title} @ {self.hearing_time} on {self.hearing_date}"


class LegalUpdate(models.Model):
    """
    Home screen: RECENT UPDATES section.
    e.g. "SC issues guidelines on live-streaming" - 2h ago
    Color-coded by urgency.
    """
    URGENCY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    urgency = models.CharField(max_length=10, choices=URGENCY_LEVELS, default='medium')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'legal_updates'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


# ══════════════════════════════════════════════════════════════════════════════
# NETWORKING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class Connection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('blocked', 'Blocked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_connections')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_connections')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'connections'
        unique_together = ('sender', 'receiver')

    def __str__(self):
        return f"{self.sender} → {self.receiver} [{self.status}]"


class Follow(models.Model):
    """Non-mutual follow — Feed screen: People to Follow sidebar."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'follows'
        unique_together = ('follower', 'following')


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGING SYSTEM
# Chat screen features: pinned chats, All/Direct/Groups/Pinned tabs
# ══════════════════════════════════════════════════════════════════════════════

class ChatRoom(models.Model):
    ROOM_TYPES = [
        ('direct', 'Direct Message'),
        ('group', 'Group Chat'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPES, default='direct')
    name = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    group_icon = models.ImageField(upload_to='group_icons/', blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_rooms')
    participants = models.ManyToManyField(User, through='ChatParticipant', related_name='chat_rooms')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_rooms'
        ordering = ['-updated_at']

    def __str__(self):
        return f"Room({self.room_type}): {self.name or self.id}"


class ChatParticipant(models.Model):
    ROLES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
    ]

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='room_participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_participations')
    role = models.CharField(max_length=10, choices=ROLES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    # Chat screen: Pinned tab — user can pin a specific chat
    is_pinned = models.BooleanField(default=False)

    class Meta:
        db_table = 'chat_participants'
        unique_together = ('room', 'user')


class Message(models.Model):
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('pdf', 'PDF Document'),
        ('doc', 'Word Document'),
        ('voice', 'Voice Note'),
        ('system', 'System Message'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_messages')
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text')
    content = models.TextField(blank=True)
    file = models.FileField(upload_to='chat_files/', blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)

    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')

    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']

    def __str__(self):
        return f"Msg[{self.message_type}] by {self.sender} in {self.room}"


class MessageReadReceipt(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'message_read_receipts'
        unique_together = ('message', 'user')


# ══════════════════════════════════════════════════════════════════════════════
# COURT CHANNELS / COMMUNITIES
# Channel screen: sub-channels, pinned messages, react+reply on channel posts
# ══════════════════════════════════════════════════════════════════════════════

class Channel(models.Model):
    CHANNEL_TYPES = [
        ('court', 'Court Channel'),
        ('practice_area', 'Practice Area'),
        ('state', 'State Bar'),
        ('general', 'General Community'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=200)
    description = models.TextField(blank=True)
    channel_type = models.CharField(max_length=20, choices=CHANNEL_TYPES, default='court')
    icon = models.ImageField(upload_to='channel_icons/', blank=True, null=True)
    cover = models.ImageField(upload_to='channel_covers/', blank=True, null=True)
    court_name = models.CharField(max_length=200, blank=True)  # e.g. "Supreme Court of India"
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    is_official = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    # Channel screen: pinned message banner at top
    pinned_message = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_channels')
    member_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'channels'
        ordering = ['-member_count']

    def __str__(self):
        return self.name


class SubChannel(models.Model):
    """
    Channel screen: sub-channels inside a parent channel.
    e.g. Supreme Court of India → Daily Cause List, Latest Judgments, General Discussion, Circulars & Notices
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='sub_channels')
    name = models.CharField(max_length=200)          # "Daily Cause List"
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    unread_count = models.PositiveIntegerField(default=0)  # Badge number on channel list
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sub_channels'
        unique_together = ('parent', 'slug')
        ordering = ['name']

    def __str__(self):
        return f"{self.parent.name} → {self.name}"


class ChannelMembership(models.Model):
    ROLES = [
        ('member', 'Member'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
    ]

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_memberships')
    role = models.CharField(max_length=15, choices=ROLES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)
    is_muted = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'channel_memberships'
        unique_together = ('channel', 'user')


class ChannelPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='posts')
    # Optional: post in a sub-channel
    sub_channel = models.ForeignKey(SubChannel, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_posts')
    content = models.TextField()
    attachment = models.FileField(upload_to='channel_attachments/', blank=True, null=True)
    attachment_type = models.CharField(max_length=20, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_announcement = models.BooleanField(default=False)
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'channel_posts'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"ChannelPost in {self.channel.name} by {self.author}"


class ChannelPostComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(ChannelPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='channel_comments')
    content = models.TextField()
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'channel_post_comments'
        ordering = ['created_at']


class ChannelPostLike(models.Model):
    post = models.ForeignKey(ChannelPost, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'channel_post_likes'
        unique_together = ('post', 'user')


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY FEED
# Feed screen: hashtags, trending topics, save/share, post types
# ══════════════════════════════════════════════════════════════════════════════

class Hashtag(models.Model):
    """
    Feed screen: Trending Now section + hashtags on posts.
    e.g. #SupremeCourt (384 posts today), #BailReform (142 posts)
    """
    name = models.CharField(max_length=100, unique=True)   # 'SupremeCourt' (without #)
    post_count = models.PositiveIntegerField(default=0)    # Trending count
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hashtags'
        ordering = ['-post_count']

    def __str__(self):
        return f"#{self.name}"


class Post(models.Model):
    POST_TYPES = [
        ('text', 'Text'),
        ('legal_update', 'Legal Update'),
        ('court_news', 'Court News'),
        ('media', 'Media Post'),
        ('article', 'Article'),        # Feed: "Article" badge on Kabir Das post
        ('judgment', 'Judgment'),
        ('document', 'Document'),
    ]

    REACT_TYPES = [
        ('like', '👍 Like'),
        ('insightful', '💡 Insightful'),
        ('support', '🤝 Support'),
        ('celebrate', '🎉 Celebrate'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    post_type = models.CharField(max_length=20, choices=POST_TYPES, default='text')
    content = models.TextField()
    media = models.FileField(upload_to='post_media/', blank=True, null=True)
    media_type = models.CharField(max_length=20, blank=True)

    # Feed: hashtags on posts (e.g. #SupremeCourt #JudicialReform #LiveStreaming)
    hashtags = models.ManyToManyField(Hashtag, blank=True, related_name='posts')

    # Visibility
    is_public = models.BooleanField(default=True)

    # Stats (cached)
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'posts'
        ordering = ['-created_at']

    def __str__(self):
        return f"Post by {self.author.full_name} [{self.post_type}]"


class PostReaction(models.Model):
    REACT_TYPES = [
        ('like', 'Like'),
        ('insightful', 'Insightful'),
        ('support', 'Support'),
        ('celebrate', 'Celebrate'),
    ]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_reactions')
    reaction_type = models.CharField(max_length=15, choices=REACT_TYPES, default='like')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_reactions'
        unique_together = ('post', 'user')


class PostComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_comments')
    content = models.TextField()
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    like_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'post_comments'
        ordering = ['created_at']


class PostCommentLike(models.Model):
    comment = models.ForeignKey(PostComment, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_comment_likes'
        unique_together = ('comment', 'user')


class SavedPost(models.Model):
    """Feed screen: Save button on posts."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_posts')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'saved_posts'
        unique_together = ('user', 'post')


class PostShare(models.Model):
    """Feed screen: Share count tracking."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shared_posts')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='shares')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_shares'


# ══════════════════════════════════════════════════════════════════════════════
# CASE DISCUSSION GROUPS
# ══════════════════════════════════════════════════════════════════════════════

class CaseGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    case_number = models.CharField(max_length=100, blank=True)
    court = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_case_groups')
    is_invite_only = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'case_groups'

    def __str__(self):
        return f"Case Group: {self.name}"


class GroupMembership(models.Model):
    ROLES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
    ]

    group = models.ForeignKey(CaseGroup, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='case_group_memberships')
    role = models.CharField(max_length=10, choices=ROLES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'group_memberships'
        unique_together = ('group', 'user')


class GroupDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(CaseGroup, on_delete=models.CASCADE, related_name='documents')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    file = models.FileField(upload_to='case_documents/')
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'group_documents'
        ordering = ['-created_at']


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

class Notification(models.Model):
    NOTIF_TYPES = [
        ('message', 'New Message'),
        ('connection_request', 'Connection Request'),
        ('connection_accepted', 'Connection Accepted'),
        ('channel_update', 'Channel Update'),
        ('mention', 'Mention'),
        ('reply', 'Reply'),
        ('reaction', 'Post Reaction'),
        ('comment', 'Comment'),
        ('verification_approved', 'Verification Approved'),
        ('verification_rejected', 'Verification Rejected'),
        ('follow', 'New Follower'),
        ('post', 'New Post'),
        ('hearing_reminder', 'Hearing Reminder'),   # Home: Today's Hearings reminder
        ('legal_update', 'Legal Update'),           # Home: Recent Updates push
        ('system', 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notif_type = models.CharField(max_length=30, choices=NOTIF_TYPES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"Notif[{self.notif_type}] → {self.recipient.email}"


# ══════════════════════════════════════════════════════════════════════════════
# REPORTS & MODERATION
# ══════════════════════════════════════════════════════════════════════════════

class Report(models.Model):
    REPORT_TYPES = [
        ('user', 'User'),
        ('post', 'Post'),
        ('message', 'Message'),
        ('channel', 'Channel'),
        ('comment', 'Comment'),
    ]

    REASONS = [
        ('spam', 'Spam'),
        ('harassment', 'Harassment'),
        ('fake_profile', 'Fake Profile'),
        ('misleading', 'Misleading Information'),
        ('inappropriate', 'Inappropriate Content'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='filed_reports')
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    reason = models.CharField(max_length=30, choices=REASONS)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    target_id = models.UUIDField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reports')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reports'
        ordering = ['-created_at']

    def __str__(self):
        return f"Report[{self.report_type}] by {self.reporter.email} – {self.status}"