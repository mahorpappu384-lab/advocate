"""
Seed script - advocates aur channels create karta hai.

RUN:
python seed_data.py
"""

import os
import django

# =========================================================
# DJANGO SETUP
# =========================================================

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()

# =========================================================
# IMPORTS
# =========================================================

from django.utils.text import slugify
from api.models import User, AdvocateProfile, Channel, ChannelMembership

print("\n" + "=" * 60)
print("SEED SCRIPT STARTING...")
print("=" * 60)

# =========================================================
# 1. ADVOCATES CREATE
# =========================================================

print("\n[1/3] Creating advocate users...\n")

advocates_data = [
    {
        'username': 'adv_sharma',
        'email': 'sharma@test.com',
        'full_name': 'Rajesh Sharma',
        'city': 'Delhi',
        'state': 'Delhi',
        'specializations': ['criminal', 'civil'],
        'courts_practiced': ['supreme_court', 'high_court'],
        'years_of_experience': 12,
        'bio': 'Senior criminal lawyer with 12 years of experience in Supreme Court.',
        'tagline': 'Justice for all, always.',
        'bar_council_id': 'BAR-DL-2012-001',
    },
    {
        'username': 'adv_mehta',
        'email': 'mehta@test.com',
        'full_name': 'Priya Mehta',
        'city': 'Mumbai',
        'state': 'Maharashtra',
        'specializations': ['corporate', 'tax'],
        'courts_practiced': ['high_court', 'tribunal'],
        'years_of_experience': 8,
        'bio': 'Corporate law specialist handling mergers, acquisitions and tax disputes.',
        'tagline': 'Protecting your business, legally.',
        'bar_council_id': 'BAR-MH-2016-002',
    },
    {
        'username': 'adv_khan',
        'email': 'khan@test.com',
        'full_name': 'Imran Khan',
        'city': 'Hyderabad',
        'state': 'Telangana',
        'specializations': ['family', 'property'],
        'courts_practiced': ['district_court', 'family_court'],
        'years_of_experience': 5,
        'bio': 'Family law and property dispute expert.',
        'tagline': 'Resolving family matters with sensitivity.',
        'bar_council_id': 'BAR-TS-2019-003',
    },
    {
        'username': 'adv_gupta',
        'email': 'gupta@test.com',
        'full_name': 'Sunita Gupta',
        'city': 'Bangalore',
        'state': 'Karnataka',
        'specializations': ['cyber', 'intellectual_property'],
        'courts_practiced': ['high_court', 'district_court'],
        'years_of_experience': 6,
        'bio': 'Cyber law and IP rights specialist for tech startups.',
        'tagline': 'Your digital rights are my priority.',
        'bar_council_id': 'BAR-KA-2018-004',
    },
]

created_advocates = []

for data in advocates_data:

    user, was_created = User.objects.get_or_create(
        username=data['username'],
        defaults={
            'email': data['email'],
            'full_name': data['full_name'],
            'is_verified': True,
            'is_advocate': True,
            'advocate_status': 'approved',
            'is_active': True,
        }
    )

    if was_created:
        user.set_password('Test@1234')
        user.save()
        print(f"Created user: {user.username}")
    else:
        user.is_advocate = True
        user.advocate_status = 'approved'
        user.is_verified = True
        user.save(update_fields=[
            'is_advocate',
            'advocate_status',
            'is_verified'
        ])
        print(f"Updated existing user: {user.username}")

    profile, _ = AdvocateProfile.objects.get_or_create(user=user)

    profile.city = data['city']
    profile.state = data['state']
    profile.specializations = data['specializations']
    profile.courts_practiced = data['courts_practiced']
    profile.years_of_experience = data['years_of_experience']
    profile.bio = data['bio']
    profile.tagline = data['tagline']
    profile.bar_council_id = data['bar_council_id']
    profile.is_public = True

    profile.save()

    created_advocates.append(user)

print(f"\nTotal advocates: {len(created_advocates)}")


# =========================================================
# 2. CHANNELS CREATE
# =========================================================

print("\n[2/3] Creating channels...\n")

admin_user = created_advocates[0]

channels_data = [
    {
        'name': 'Supreme Court of India',
        'description': 'Official channel for Supreme Court updates and legal news.',
        'channel_type': 'court',
        'court_name': 'Supreme Court of India',
        'city': 'New Delhi',
        'state': 'Delhi',
        'is_official': True,
    },
    {
        'name': 'Delhi High Court',
        'description': 'Updates related to Delhi High Court.',
        'channel_type': 'court',
        'court_name': 'Delhi High Court',
        'city': 'Delhi',
        'state': 'Delhi',
        'is_official': True,
    },
    {
        'name': 'Criminal Law Community',
        'description': 'Discuss criminal law and IPC sections.',
        'channel_type': 'practice_area',
        'court_name': '',
        'city': '',
        'state': '',
        'is_official': False,
    },
    {
        'name': 'Corporate and Tax Law',
        'description': 'Corporate and tax law discussions.',
        'channel_type': 'practice_area',
        'court_name': '',
        'city': '',
        'state': '',
        'is_official': False,
    },
    {
        'name': 'Delhi Bar Association',
        'description': 'Community for advocates practicing in Delhi.',
        'channel_type': 'state',
        'court_name': '',
        'city': 'Delhi',
        'state': 'Delhi',
        'is_official': False,
    },
    {
        'name': 'Legal Updates India',
        'description': 'Latest legal news and judgments.',
        'channel_type': 'general',
        'court_name': '',
        'city': '',
        'state': '',
        'is_official': True,
    },
]

created_channels = []

for data in channels_data:

    slug = slugify(data['name'])

    existing = Channel.objects.filter(slug=slug).first()

    if existing:
        print(f"Already exists: {data['name']}")
        created_channels.append(existing)
        continue

    channel = Channel.objects.create(
        name=data['name'],
        slug=slug,
        description=data['description'],
        channel_type=data['channel_type'],
        court_name=data.get('court_name', ''),
        city=data.get('city', ''),
        state=data.get('state', ''),
        is_official=data.get('is_official', False),
        created_by=admin_user,
        member_count=0,
    )

    print(f"Created channel: {channel.name}")

    created_channels.append(channel)

print(f"\nTotal channels: {len(created_channels)}")


# =========================================================
# 3. MEMBERSHIPS
# =========================================================

print("\n[3/3] Adding advocates to channels...\n")

for channel in created_channels:

    added = 0

    for i, user in enumerate(created_advocates):

        role = 'admin' if i == 0 else 'member'

        membership, was_created = ChannelMembership.objects.get_or_create(
            channel=channel,
            user=user,
            defaults={
                'role': role
            }
        )

        if was_created:
            added += 1
            channel.member_count += 1

    channel.save(update_fields=['member_count'])

    print(f"{channel.name}: +{added} members")


# =========================================================
# SUMMARY
# =========================================================

print("\n" + "=" * 60)
print("SEED COMPLETE!")
print("=" * 60)

print(
    f"Advocates : "
    f"{User.objects.filter(is_advocate=True, advocate_status='approved').count()}"
)

print(f"Channels  : {Channel.objects.count()}")

print("\nPassword for all users: Test@1234")

print("\nLOGIN CREDENTIALS:\n")

for adv in created_advocates:
    print(
        f"username: {adv.username} | password: Test@1234"
    )

print("\nDONE\n")