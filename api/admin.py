from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import (
    User, OTP, AdvocateProfile, AdvocateEducation, AdvocateExperience,
    AdvocateAchievement, Connection, Follow,
    ChatRoom, ChatParticipant, Message,
    Channel, ChannelMembership, ChannelPost,
    Post, PostComment, PostReaction,
    CaseGroup, GroupMembership, GroupDocument,
    Notification, Report,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'full_name', 'is_verified', 'is_advocate',
                    'advocate_status', 'is_active', 'date_joined']
    list_filter = ['is_active', 'is_verified', 'is_advocate', 'advocate_status', 'is_staff']
    search_fields = ['username', 'email', 'full_name']
    ordering = ['-date_joined']
    readonly_fields = ['id', 'date_joined', 'last_seen']

    fieldsets = (
        (None, {'fields': ('id', 'username', 'email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'phone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                    'is_verified', 'is_advocate', 'advocate_status')}),
        ('Activity', {'fields': ('date_joined', 'last_seen', 'is_online')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'full_name', 'password1', 'password2'),
        }),
    )


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'purpose', 'code', 'is_used', 'created_at', 'expires_at']
    list_filter = ['purpose', 'is_used']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['id', 'created_at']


class AdvocateEducationInline(admin.TabularInline):
    model = AdvocateEducation
    extra = 0


class AdvocateExperienceInline(admin.TabularInline):
    model = AdvocateExperience
    extra = 0


@admin.register(AdvocateProfile)
class AdvocateProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'bar_council_id', 'city', 'state',
                    'years_of_experience', 'is_public', 'connection_count']
    list_filter = ['is_public', 'state']
    search_fields = ['user__username', 'user__full_name', 'bar_council_id', 'city']
    readonly_fields = ['connection_count', 'follower_count', 'post_count']
    inlines = [AdvocateEducationInline, AdvocateExperienceInline]

    def bar_council_image_preview(self, obj):
        if obj.bar_council_id_image:
            return format_html('<img src="{}" height="100"/>', obj.bar_council_id_image.url)
        return "—"
    bar_council_image_preview.short_description = 'Bar Council ID'


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ['sender', 'receiver', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['sender__username', 'receiver__username']


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ['follower', 'following', 'created_at']
    search_fields = ['follower__username', 'following__username']


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'room_type', 'name', 'created_by', 'created_at']
    list_filter = ['room_type']
    search_fields = ['name', 'created_by__username']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'room', 'message_type', 'is_deleted', 'created_at']
    list_filter = ['message_type', 'is_deleted']
    search_fields = ['sender__username', 'content']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ['name', 'channel_type', 'city', 'state', 'is_official',
                    'is_private', 'member_count']
    list_filter = ['channel_type', 'is_official', 'is_private']
    search_fields = ['name', 'city', 'state']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ChannelPost)
class ChannelPostAdmin(admin.ModelAdmin):
    list_display = ['author', 'channel', 'is_pinned', 'is_announcement',
                    'like_count', 'comment_count', 'created_at']
    list_filter = ['is_pinned', 'is_announcement']


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['author', 'post_type', 'is_public', 'like_count',
                    'comment_count', 'created_at']
    list_filter = ['post_type', 'is_public']
    search_fields = ['author__username', 'content']
    readonly_fields = ['id', 'like_count', 'comment_count', 'share_count']


@admin.register(CaseGroup)
class CaseGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_by', 'case_number', 'court',
                    'is_invite_only', 'is_active', 'created_at']
    list_filter = ['is_invite_only', 'is_active']
    search_fields = ['name', 'case_number', 'created_by__username']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'notif_type', 'title', 'is_read', 'created_at']
    list_filter = ['notif_type', 'is_read']
    search_fields = ['recipient__username', 'title']
    readonly_fields = ['id', 'created_at']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['reporter', 'report_type', 'reason', 'status', 'created_at']
    list_filter = ['report_type', 'reason', 'status']
    search_fields = ['reporter__username']
    readonly_fields = ['id', 'created_at']

    actions = ['mark_resolved', 'mark_dismissed']

    def mark_resolved(self, request, queryset):
        queryset.update(status='resolved', reviewed_by=request.user)
    mark_resolved.short_description = "Mark selected reports as Resolved"

    def mark_dismissed(self, request, queryset):
        queryset.update(status='dismissed', reviewed_by=request.user)
    mark_dismissed.short_description = "Mark selected reports as Dismissed"