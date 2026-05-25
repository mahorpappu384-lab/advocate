"""
Django Channels WebSocket URL routing.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Real-time chat: ws://host/ws/chat/<room_id>/
    re_path(r'ws/chat/(?P<room_id>\w+)/$', consumers.ChatConsumer.as_asgi()),

    # Real-time notifications: ws://host/ws/notifications/
    re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
]