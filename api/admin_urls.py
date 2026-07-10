"""
admin_urls.py
══════════════════════════════════════════════════════════════════════════════
URL routing for admin_views.py (PERFECT SUPER-ADMIN BACKEND).

Ismein admin_views.py ke SAARE views wire kiye gaye hain — bootstrap/login se
lekar har model ke List/Detail views aur moderation actions tak — taaki tum
apna HTML/JS admin dashboard bana ke seedha in endpoints se connect kar sako.

HOW TO PLUG THIS IN
──────────────────────────────────────────────────────────────────────────────
1) Is file ko apni app ke folder mein rakho (jahan admin_views.py hai),
   e.g.  yourapp/admin_urls.py

2) Apni project-level urls.py (jahan main urlpatterns hai) mein add karo:

       from django.urls import path, include

       urlpatterns = [
           ...
           path('api/admin/', include('yourapp.admin_urls')),
       ]

   NOTE: agar tumhari existing app-level urls.py (jo tumne pehle bheji thi)
   mein already 'admin/...' paths hain jo `views.Admin...` (purane/simple
   views) ko point karti hain, unhe wahan se HATA do — warna Django do baar
   register hone se confusion/clash hoga. Yeh naya file poora admin module
   independently handle karta hai (naya, zyada powerful admin_views.py).

3) Frontend/HTML se call karte waqt base URL hoga:
       https://yourdomain.com/api/admin/...

   Har protected endpoint pe header bhejo:
       Authorization: Bearer <access_token>   (AdminLoginView se mila JWT)

══════════════════════════════════════════════════════════════════════════════
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import admin_views as av

app_name = 'admin_panel'

urlpatterns = [

    # ══════════════════════════════════════════════════════════════════════
    # 1) BOOTSTRAP & AUTH
    # ══════════════════════════════════════════════════════════════════════
    path('bootstrap/',                     av.AdminBootstrapCreateView.as_view(),       name='bootstrap'),
    path('login/',                         av.AdminLoginView.as_view(),                 name='login'),
    path('token/refresh/',                 TokenRefreshView.as_view(),                  name='token-refresh'),

    # ══════════════════════════════════════════════════════════════════════
    # 2) DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    path('dashboard/',                     av.AdminDashboardStatsView.as_view(),        name='dashboard'),

    # ══════════════════════════════════════════════════════════════════════
    # 3) USERS
    # ══════════════════════════════════════════════════════════════════════
    path('users/',                         av.AdminUserListView.as_view(),              name='user-list'),
    path('users/<uuid:pk>/',               av.AdminUserDetailView.as_view(),            name='user-detail'),
    path('users/<uuid:pk>/ban/',           av.AdminBanUserView.as_view(),               name='user-ban'),
    path('users/<uuid:pk>/unban/',         av.AdminUnbanUserView.as_view(),             name='user-unban'),
    path('users/<uuid:pk>/set-staff/',     av.AdminSetStaffView.as_view(),              name='user-set-staff'),
    path('users/<uuid:pk>/set-superuser/', av.AdminSetSuperuserView.as_view(),          name='user-set-superuser'),
    path('users/<uuid:pk>/reset-password/', av.AdminResetUserPasswordView.as_view(),    name='user-reset-password'),

    # ══════════════════════════════════════════════════════════════════════
    # 4) ADVOCATE VERIFICATIONS
    # ══════════════════════════════════════════════════════════════════════
    path('verifications/',                       av.AdminPendingVerificationsView.as_view(), name='verifications'),
    path('verifications/<uuid:user_id>/decide/', av.AdminVerifyAdvocateView.as_view(),       name='verification-decide'),

    # ══════════════════════════════════════════════════════════════════════
    # 5) ADVOCATE PROFILE + EDUCATION/EXPERIENCE/ACHIEVEMENTS
    # ══════════════════════════════════════════════════════════════════════
    path('advocate-profiles/',             av.AdminAdvocateProfileListView.as_view(),   name='advocate-profile-list'),
    # NOTE: AdvocateProfile has NO explicit UUID id field in models.py — it uses
    # Django's default integer AutoField (1, 2, 3, ...), unlike every other model
    # here. So this one route MUST use <int:pk>, not <uuid:pk>.
    path('advocate-profiles/<int:pk>/',    av.AdminAdvocateProfileDetailView.as_view(), name='advocate-profile-detail'),
    path('advocate-education/',            av.AdminAdvocateEducationListView.as_view(), name='advocate-education-list'),
    path('advocate-experience/',           av.AdminAdvocateExperienceListView.as_view(), name='advocate-experience-list'),
    path('advocate-achievements/',         av.AdminAdvocateAchievementListView.as_view(), name='advocate-achievement-list'),

    # ══════════════════════════════════════════════════════════════════════
    # 6) CHANNELS
    # ══════════════════════════════════════════════════════════════════════
    path('channels/',                      av.AdminChannelListView.as_view(),           name='channel-list'),
    path('channels/<uuid:pk>/',            av.AdminChannelDetailView.as_view(),         name='channel-detail'),
    path('sub-channels/',                  av.AdminSubChannelListView.as_view(),        name='sub-channel-list'),
    path('channel-memberships/',           av.AdminChannelMembershipListView.as_view(), name='channel-membership-list'),
    path('channel-posts/',                 av.AdminChannelPostListView.as_view(),       name='channel-post-list'),
    path('channel-posts/<uuid:pk>/',       av.AdminChannelPostDetailView.as_view(),     name='channel-post-detail'),
    path('channel-post-comments/',         av.AdminChannelPostCommentListView.as_view(), name='channel-post-comment-list'),
    path('channel-post-comments/<uuid:pk>/', av.AdminChannelPostCommentDetailView.as_view(), name='channel-post-comment-detail'),

    # ══════════════════════════════════════════════════════════════════════
    # 7) COMMUNITY FEED (Posts)
    # ══════════════════════════════════════════════════════════════════════
    path('hashtags/',                      av.AdminHashtagListView.as_view(),           name='hashtag-list'),
    path('posts/',                         av.AdminPostListView.as_view(),              name='post-list'),
    path('posts/<uuid:pk>/',               av.AdminPostDetailView.as_view(),            name='post-detail'),
    path('post-comments/',                 av.AdminPostCommentListView.as_view(),       name='post-comment-list'),
    path('post-comments/<uuid:pk>/',       av.AdminPostCommentDetailView.as_view(),     name='post-comment-detail'),

    # ══════════════════════════════════════════════════════════════════════
    # 8) REPORTS & MODERATION
    # ══════════════════════════════════════════════════════════════════════
    path('reports/',                       av.AdminReportListView.as_view(),            name='report-list'),
    path('reports/<uuid:pk>/',             av.AdminReportDetailView.as_view(),          name='report-detail'),
    path('reports/<uuid:pk>/resolve/',     av.AdminReportResolveView.as_view(),         name='report-resolve'),

    # ══════════════════════════════════════════════════════════════════════
    # 9) NETWORKING (Connections / Follows)
    # ══════════════════════════════════════════════════════════════════════
    path('connections/',                   av.AdminConnectionListView.as_view(),        name='connection-list'),
    path('follows/',                       av.AdminFollowListView.as_view(),            name='follow-list'),

    # ══════════════════════════════════════════════════════════════════════
    # 10) CHAT (rooms/messages)
    # ══════════════════════════════════════════════════════════════════════
    path('chat-rooms/',                    av.AdminChatRoomListView.as_view(),          name='chat-room-list'),
    path('chat-rooms/<uuid:pk>/',          av.AdminChatRoomDetailView.as_view(),        name='chat-room-detail'),
    path('messages/',                      av.AdminMessageListView.as_view(),           name='message-list'),
    path('messages/<uuid:pk>/',            av.AdminMessageDetailView.as_view(),         name='message-detail'),

    # ══════════════════════════════════════════════════════════════════════
    # 11) CASE GROUPS
    # ══════════════════════════════════════════════════════════════════════
    path('case-groups/',                   av.AdminCaseGroupListView.as_view(),         name='case-group-list'),
    path('case-groups/<uuid:pk>/',         av.AdminCaseGroupDetailView.as_view(),       name='case-group-detail'),
    path('group-memberships/',             av.AdminGroupMembershipListView.as_view(),   name='group-membership-list'),
    path('group-documents/',               av.AdminGroupDocumentListView.as_view(),     name='group-document-list'),

    # ══════════════════════════════════════════════════════════════════════
    # 12) NOTIFICATIONS
    # ══════════════════════════════════════════════════════════════════════
    path('notifications/',                 av.AdminNotificationListView.as_view(),      name='notification-list'),

    # ══════════════════════════════════════════════════════════════════════
    # 13) HEARINGS & LEGAL UPDATES
    # ══════════════════════════════════════════════════════════════════════
    path('hearings/',                      av.AdminHearingListView.as_view(),           name='hearing-list'),
    path('legal-updates/',                 av.AdminLegalUpdateListView.as_view(),       name='legal-update-list'),
    path('legal-updates/<uuid:pk>/',       av.AdminLegalUpdateDetailView.as_view(),     name='legal-update-detail'),
    path('legal-updates/create/',          av.AdminLegalUpdateCreateView.as_view(),     name='legal-update-create'),

    # ══════════════════════════════════════════════════════════════════════
    # 14) STORIES
    # ══════════════════════════════════════════════════════════════════════
    path('stories/',                       av.AdminStoryListView.as_view(),             name='story-list'),
    path('stories/<uuid:pk>/',             av.AdminStoryDetailView.as_view(),           name='story-detail'),

    # ══════════════════════════════════════════════════════════════════════
    # 15) OTP MONITORING (masked codes)
    # ══════════════════════════════════════════════════════════════════════
    path('otps/',                          av.AdminOTPListView.as_view(),               name='otp-list'),
]