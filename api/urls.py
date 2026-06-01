"""
Advocate App - All API URL Patterns
LegalConnect UI ke saath 100% aligned
Base: /api/

New endpoints added:
- /api/home/dashboard/             — Home stats + hearings + updates
- /api/hearings/                   — Today's Hearings CRUD
- /api/legal-updates/              — Recent Updates list
- /api/users/me/presence/          — Online/Away/Offline toggle
- /api/users/me/preferences/       — Theme, accent, notifications, privacy
- /api/chat/rooms/<id>/pin/        — Pin/unpin chat (Pinned tab)
- /api/channels/<id>/sub-channels/ — Sub-channels (Daily Cause List, etc.)
- /api/feed/trending/              — Trending hashtags (Feed sidebar)
- /api/feed/saved/                 — Saved posts list
- /api/feed/<id>/save/             — Save/unsave a post
- /api/feed/<id>/share/            — Record a share
- /api/admin/legal-updates/        — Admin: create legal updates
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register(r'advocates/education',     views.AdvocateEducationViewSet,    basename='education')
router.register(r'advocates/experience',    views.AdvocateExperienceViewSet,   basename='experience')
router.register(r'advocates/achievements',  views.AdvocateAchievementViewSet,  basename='achievements')

urlpatterns = [

    path('', include(router.urls)),

    # ══════════════════════════════════════════════════════════════════════════
    # AUTH  (unchanged as requested)
    # ══════════════════════════════════════════════════════════════════════════
    path('auth/register/',        views.RegisterView.as_view(),       name='register'),
    path('auth/login/',           views.LoginView.as_view(),          name='login'),
    path('auth/logout/',          views.LogoutView.as_view(),         name='logout'),
    path('auth/token/refresh/',   TokenRefreshView.as_view(),         name='token_refresh'),
    path('auth/verify-otp/',      views.VerifyOTPView.as_view(),      name='verify-otp'),
    path('auth/resend-otp/',      views.ResendOTPView.as_view(),      name='resend-otp'),
    path('auth/forgot-password/', views.ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/reset-password/',  views.ResetPasswordView.as_view(),  name='reset-password'),
    path('auth/change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('auth/delete-account/',  views.DeleteAccountView.as_view(),  name='delete-account'),
    path('health/', views.HealthView.as_view(), name='health'),

    # ══════════════════════════════════════════════════════════════════════════
    # USERS
    # ══════════════════════════════════════════════════════════════════════════
    path('users/me/',                  views.MyProfileView.as_view(),       name='my-profile'),
    path('users/me/presence/',         views.UserPresenceView.as_view(),     name='user-presence'),       # Profile: Online/Away/Offline
    path('users/me/preferences/',      views.UserPreferencesView.as_view(),  name='user-preferences'),    # Profile: theme, notifs, privacy
    path('users/<uuid:pk>/',           views.UserDetailView.as_view(),       name='user-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # HOME SCREEN
    # ══════════════════════════════════════════════════════════════════════════
    path('home/dashboard/',            views.HomeDashboardView.as_view(),    name='home-dashboard'),       # Stats + hearings + updates
    path('hearings/',                  views.HearingListCreateView.as_view(),name='hearings'),             # Today's Hearings CRUD
    path('hearings/<uuid:pk>/',        views.HearingDetailView.as_view(),    name='hearing-detail'),
    path('legal-updates/',             views.LegalUpdateListView.as_view(),  name='legal-updates'),        # Recent Updates

    # ══════════════════════════════════════════════════════════════════════════
    # ADVOCATE PROFILES
    # ══════════════════════════════════════════════════════════════════════════
    path('advocates/',                     views.AdvocateProfileListView.as_view(),  name='advocate-list'),
    path('advocates/me/',                  views.MyAdvocateProfileView.as_view(),    name='my-advocate-profile'),
    path('advocates/me/onboarding/',       views.AdvocateOnboardingView.as_view(),   name='advocate-onboarding'),
    path('advocates/verify/',              views.AdvocateVerificationView.as_view(), name='advocate-verify'),
    path('advocates/<uuid:user_id>/',      views.AdvocateProfileDetailView.as_view(),name='advocate-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # CONNECTIONS & FOLLOW
    # ══════════════════════════════════════════════════════════════════════════
    path('connections/',                       views.ConnectionListView.as_view(),       name='connection-list'),
    path('connections/pending/',               views.PendingConnectionsView.as_view(),   name='pending-connections'),
    path('connections/send/',                  views.SendConnectionRequestView.as_view(),name='send-connection'),
    path('connections/<uuid:pk>/',             views.ConnectionDetailView.as_view(),     name='connection-detail'),
    path('follow/<uuid:user_id>/',             views.FollowView.as_view(),               name='follow'),
    path('network/suggested/',                 views.SuggestedAdvocatesView.as_view(),   name='suggested'),      # Feed: People to Follow
    path('chat/presign/', views.R2PresignedUploadView.as_view(), name='r2-presign'),
    path('feed/presign/', views.PostMediaPresignView.as_view(), name='post-media-presign'),

    # ══════════════════════════════════════════════════════════════════════════
    # CHAT
    # Chat screen: All/Direct/Groups/Pinned tabs, pin/unpin
    # ══════════════════════════════════════════════════════════════════════════
    path('chat/rooms/<uuid:room_id>/', views.ChatRoomDetailView.as_view(), name='chat-room-detail'),
    path('chat/rooms/',                              views.ChatRoomListView.as_view(),       name='chat-rooms'),          # ?tab=all|direct|group|pinned
    path('chat/rooms/direct/',                       views.CreateDirectChatView.as_view(),   name='create-direct'),
    path('chat/rooms/group/',                        views.CreateGroupChatView.as_view(),    name='create-group'),
    path('chat/rooms/<uuid:room_id>/messages/',      views.MessageListCreateView.as_view(),  name='messages'),
    path('chat/rooms/<uuid:room_id>/read/',          views.MarkMessagesReadView.as_view(),   name='mark-read'),
    path('chat/rooms/<uuid:room_id>/pin/',           views.PinChatView.as_view(),            name='pin-chat'),            # Pin/unpin chat
    path('chat/messages/<uuid:pk>/',                 views.MessageDetailView.as_view(),      name='message-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # CHANNELS
    # Channel screen: channel list, sub-channels, posts, join/leave
    # ══════════════════════════════════════════════════════════════════════════
    path('channels/',                                  views.ChannelListView.as_view(),              name='channel-list'),
    path('channels/create/',                           views.CreateChannelView.as_view(),             name='create-channel'),
    path('channels/mine/',                             views.MyChannelsView.as_view(),                name='my-channels'),
    path('channels/<uuid:id>/',                        views.ChannelDetailView.as_view(),             name='channel-detail'),
    path('channels/<uuid:id>/update/',                 views.UpdateChannelView.as_view(),             name='channel-update'),
        path('channels/<uuid:pk>/join/',                   views.JoinChannelView.as_view(),               name='join-channel'),
    path('channels/<uuid:pk>/leave/',                  views.LeaveChannelView.as_view(),              name='leave-channel'),
    path('channels/icon-presign/',                     views.ChannelIconPresignView.as_view(),         name='channel-icon-presign'),
    path('channels/<uuid:channel_id>/posts/presign/',  views.ChannelPostPresignView.as_view(),         name='channel-post-presign'),
    path('channels/<uuid:pk>/join-requests/',          views.ChannelJoinRequestListView.as_view(),     name='channel-join-requests'),
    path('channels/<uuid:pk>/join-requests/<uuid:user_id>/<str:action>/', views.ChannelJoinRequestActionView.as_view(), name='channel-join-request-action'),
    path('channels/<uuid:channel_id>/sub-channels/',   views.SubChannelListCreateView.as_view(),      name='sub-channels'),        # Sub-channels
    path('channels/<uuid:channel_id>/members/',        views.ChannelMembersListView.as_view(),         name='channel-members'),      # Members list
    path('channels/<uuid:channel_id>/posts/',          views.ChannelPostListCreateView.as_view(),     name='channel-posts'),       # ?sub_channel=<id>
    path('channels/posts/<uuid:pk>/like/',             views.ChannelPostLikeView.as_view(),           name='channel-post-like'),
    path('channels/posts/<uuid:post_id>/comments/',    views.ChannelPostCommentView.as_view(),        name='channel-comments'),

    # ══════════════════════════════════════════════════════════════════════════
    # FEED & POSTS
    # Feed screen: hashtags, trending, save, share
    # ══════════════════════════════════════════════════════════════════════════
    path('feed/',                           views.FeedListCreateView.as_view(),    name='feed'),               # ?hashtag=SupremeCourt
    path('feed/trending/',                  views.TrendingHashtagsView.as_view(),  name='trending-hashtags'),   # Trending Now sidebar
    path('feed/saved/',                     views.SavedPostListView.as_view(),     name='saved-posts'),         # Saved posts
    path('feed/<uuid:pk>/',                 views.PostDetailView.as_view(),        name='post-detail'),
    path('feed/<uuid:pk>/react/',           views.PostReactView.as_view(),         name='post-react'),
    path('feed/<uuid:pk>/save/',            views.SavePostView.as_view(),          name='save-post'),           # Save/unsave
    path('feed/<uuid:pk>/share/',           views.SharePostView.as_view(),         name='share-post'),          # Share count
    path('feed/<uuid:post_id>/comments/',   views.PostCommentView.as_view(),       name='post-comments'),

    # ══════════════════════════════════════════════════════════════════════════
    # NOTIFICATIONS
    # ══════════════════════════════════════════════════════════════════════════
    path('notifications/',                   views.NotificationListView.as_view(),           name='notifications'),
    path('notifications/unread-count/',      views.UnreadNotificationCountView.as_view(),    name='unread-count'),
    path('notifications/read-all/',          views.MarkAllNotificationsReadView.as_view(),   name='read-all'),
    path('notifications/<uuid:pk>/read/',    views.MarkNotificationReadView.as_view(),       name='read-notif'),

    # ══════════════════════════════════════════════════════════════════════════
    # CASE GROUPS
    # ══════════════════════════════════════════════════════════════════════════
    path('case-groups/',                        views.CaseGroupListCreateView.as_view(), name='case-groups'),
    path('case-groups/<uuid:pk>/',              views.CaseGroupDetailView.as_view(),     name='case-group-detail'),
    path('case-groups/<uuid:pk>/invite/',       views.InviteToCaseGroupView.as_view(),   name='invite-case-group'),
    path('case-groups/<uuid:group_id>/documents/', views.GroupDocumentView.as_view(),    name='group-docs'),

    # ══════════════════════════════════════════════════════════════════════════
    # REPORTS
    # ══════════════════════════════════════════════════════════════════════════
    path('reports/', views.ReportCreateView.as_view(), name='report'),

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN
    # ══════════════════════════════════════════════════════════════════════════
    path('admin/users/',                              views.AdminUserListView.as_view(),              name='admin-users'),
    path('admin/users/<uuid:pk>/',                    views.AdminUserDetailView.as_view(),            name='admin-user-detail'),
    path('admin/users/<uuid:pk>/ban/',                views.AdminBanUserView.as_view(),               name='admin-ban'),
    path('admin/users/<uuid:pk>/unban/',              views.AdminUnbanUserView.as_view(),             name='admin-unban'),
    path('admin/verifications/',                      views.AdminPendingVerificationsView.as_view(),  name='admin-verifications'),
    path('admin/verifications/<uuid:user_id>/approve/', views.AdminVerifyAdvocateView.as_view(),      name='admin-verify'),
    path('admin/reports/',                            views.AdminReportListView.as_view(),            name='admin-reports'),
    path('admin/reports/<uuid:pk>/resolve/',          views.AdminReportResolveView.as_view(),         name='admin-resolve'),
    path('admin/analytics/',                          views.AdminAnalyticsView.as_view(),             name='admin-analytics'),
    path('admin/channels/',                           views.AdminChannelListView.as_view(),           name='admin-channels'),
    path('admin/legal-updates/',                      views.AdminLegalUpdateView.as_view(),           name='admin-legal-updates'),  # Create Recent Updates
]