import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

django_asgi_app = get_asgi_application()

from api.routing import websocket_urlpatterns

# ✅ FIX: AuthMiddlewareStack hata diya.
# Wo Django session-cookie se scope['user'] resolve karne ki koshish karta hai —
# har WS connect attempt pe ek EXTRA sync DB query (session lookup) chalata tha,
# jiska humne use hi nahi kiya tha (consumer JWT token se khud user resolve karta hai).
# Render starter plan pe single worker (WEB_CONCURRENCY=1) + cold/slow Postgres
# ke combo mein ye extra query proxy ka WS-upgrade timeout cross kar deti thi,
# jiski wajah se browser ko "Unexpected response code: 500" milta tha —
# aur ye consumers.py ke connect() tak pohochne se PEHLE hota tha, isliye
# wahan koi log bhi nahi dikhta tha.
# Auth ab sirf consumer ke andar JWT token se hota hai — middleware ki zaroorat nahi.
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(websocket_urlpatterns),
})