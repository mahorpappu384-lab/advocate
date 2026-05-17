"""
Django signals — auto-trigger notifications on model events.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(post_save, sender=User)
def create_advocate_profile_on_register(sender, instance, created, **kwargs):
    """
    Naya user register hote hi AdvocateProfile row bana do.

    Pehle yeh sirf 'pass' tha — matlab agar koi user seedha
    /api/advocates/<userId>/ hit karta toh get_object_or_404
    404 deta tha kyunki row DB mein hoti hi nahi thi.

    Ab har naye user ka profile automatically banta hai registration pe.
    """
    if created:
        # Import here to avoid circular imports
        from .models import AdvocateProfile
        AdvocateProfile.objects.get_or_create(user=instance)