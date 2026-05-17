"""
Advocate App - All API URL Patterns
Flutter services ke saath 100% aligned
Base: /api/
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
    # AUTH  —  auth_service.dart
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
    path('users/me/',        views.MyProfileView.as_view(),   name='my-profile'),
    path('users/<uuid:pk>/', views.UserDetailView.as_view(),  name='user-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # ADVOCATE PROFILES  —  profile_service.dart
    # GET/PATCH  /api/advocates/me/
    # GET        /api/advocates/          (search)
    # GET        /api/advocates/<userId>/
    # POST       /api/advocates/verify/
    # ══════════════════════════════════════════════════════════════════════════
    path('advocates/',                     views.AdvocateProfileListView.as_view(),  name='advocate-list'),
    path('advocates/me/',                  views.MyAdvocateProfileView.as_view(),    name='my-advocate-profile'),
    path('advocates/verify/',              views.AdvocateVerificationView.as_view(), name='advocate-verify'),
    path('advocates/<uuid:user_id>/',      views.AdvocateProfileDetailView.as_view(),name='advocate-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # CONNECTIONS  —  profile_service.dart
    # GET    /api/connections/
    # POST   /api/connections/
    # GET    /api/connections/pending/
    # PATCH  /api/connections/<id>/
    # DELETE /api/connections/<id>/
    # POST   /api/follow/<userId>/
    # DELETE /api/follow/<userId>/
    # GET    /api/network/suggested/
    # ══════════════════════════════════════════════════════════════════════════
    path('connections/',                       views.ConnectionListView.as_view(),       name='connection-list'),
    path('connections/pending/',               views.PendingConnectionsView.as_view(),   name='pending-connections'),
    path('connections/send/',                  views.SendConnectionRequestView.as_view(),name='send-connection'),
    path('connections/<uuid:pk>/',             views.ConnectionDetailView.as_view(),     name='connection-detail'),
    path('follow/<uuid:user_id>/',             views.FollowView.as_view(),               name='follow'),
    path('network/suggested/',                 views.SuggestedAdvocatesView.as_view(),   name='suggested'),

    # ══════════════════════════════════════════════════════════════════════════
    # CHAT  —  chat_service.dart
    # GET    /api/chat/rooms/
    # POST   /api/chat/rooms/direct/        ← Flutter uses this exact URL
    # POST   /api/chat/rooms/group/         ← Flutter uses this exact URL
    # GET    /api/chat/rooms/<id>/messages/
    # POST   /api/chat/rooms/<id>/messages/ (file upload)
    # POST   /api/chat/rooms/<id>/read/
    # PATCH  /api/chat/messages/<id>/
    # DELETE /api/chat/messages/<id>/
    # ══════════════════════════════════════════════════════════════════════════
    path('chat/rooms/',                              views.ChatRoomListView.as_view(),    name='chat-rooms'),
    path('chat/rooms/direct/',                       views.CreateDirectChatView.as_view(),name='create-direct'),   # Flutter exact URL
    path('chat/rooms/group/',                        views.CreateGroupChatView.as_view(), name='create-group'),    # Flutter exact URL
    path('chat/rooms/<uuid:room_id>/messages/',      views.MessageListCreateView.as_view(), name='messages'),
    path('chat/rooms/<uuid:room_id>/read/',          views.MarkMessagesReadView.as_view(), name='mark-read'),
    path('chat/messages/<uuid:pk>/',                 views.MessageDetailView.as_view(),  name='message-detail'),

    # ══════════════════════════════════════════════════════════════════════════
    # CHANNELS  —  channel_service.dart
    # GET    /api/channels/
    # GET    /api/channels/<id>/
    # POST   /api/channels/<id>/join/
    # DELETE /api/channels/<id>/leave/
    # GET    /api/channels/<id>/posts/
    # POST   /api/channels/<id>/posts/
    # POST   /api/channels/posts/<id>/like/
    # POST   /api/channels/posts/<id>/comments/
    # ══════════════════════════════════════════════════════════════════════════
    path('channels/',                                  views.ChannelListView.as_view(),         name='channel-list'),
    path('channels/create/',                           views.CreateChannelView.as_view(),        name='create-channel'),
    path('channels/mine/',                             views.MyChannelsView.as_view(),           name='my-channels'),
    path('channels/<uuid:id>/',                        views.ChannelDetailView.as_view(),        name='channel-detail'),
    path('channels/<uuid:pk>/join/',                   views.JoinChannelView.as_view(),          name='join-channel'),
    path('channels/<uuid:pk>/leave/',                  views.LeaveChannelView.as_view(),         name='leave-channel'),
    path('channels/<uuid:channel_id>/posts/',          views.ChannelPostListCreateView.as_view(),name='channel-posts'),
    path('channels/posts/<uuid:pk>/like/',             views.ChannelPostLikeView.as_view(),      name='channel-post-like'),
    path('channels/posts/<uuid:post_id>/comments/',    views.ChannelPostCommentView.as_view(),   name='channel-comments'),

    # ══════════════════════════════════════════════════════════════════════════
    # FEED & POSTS  —  post_service.dart
    # Flutter uses /feed/ for BOTH feed listing AND creating posts
    # GET    /api/feed/               → home feed
    # POST   /api/feed/               → create post
    # DELETE /api/feed/<id>/
    # POST   /api/feed/<id>/react/
    # DELETE /api/feed/<id>/react/
    # GET    /api/feed/<id>/comments/
    # POST   /api/feed/<id>/comments/
    # ══════════════════════════════════════════════════════════════════════════
    path('feed/',                           views.FeedListCreateView.as_view(),  name='feed'),
    path('feed/<uuid:pk>/',                 views.PostDetailView.as_view(),      name='post-detail'),
    path('feed/<uuid:pk>/react/',           views.PostReactView.as_view(),       name='post-react'),
    path('feed/<uuid:post_id>/comments/',   views.PostCommentView.as_view(),     name='post-comments'),

    # ══════════════════════════════════════════════════════════════════════════
    # NOTIFICATIONS  —  notification_service.dart
    # GET    /api/notifications/
    # GET    /api/notifications/unread-count/
    # POST   /api/notifications/<id>/read/
    # POST   /api/notifications/read-all/
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
]