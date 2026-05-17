"""
Filter classes for search, filtering advocates, posts, channels.
"""
import django_filters
from .models import AdvocateProfile, Post, Channel


class AdvocateProfileFilter(django_filters.FilterSet):
    """
    Filters for searching advocates.
    Usage: /api/advocates/?city=Delhi&practice_area=criminal&court=supreme_court
    """
    city = django_filters.CharFilter(lookup_expr='icontains')
    state = django_filters.CharFilter(lookup_expr='icontains')
    practice_area = django_filters.CharFilter(method='filter_practice_area')
    court = django_filters.CharFilter(method='filter_court')
    language = django_filters.CharFilter(method='filter_language')
    min_experience = django_filters.NumberFilter(field_name='years_of_experience', lookup_expr='gte')
    max_experience = django_filters.NumberFilter(field_name='years_of_experience', lookup_expr='lte')
    name = django_filters.CharFilter(field_name='user__full_name', lookup_expr='icontains')

    class Meta:
        model = AdvocateProfile
        fields = ['city', 'state']

    def filter_practice_area(self, queryset, name, value):
        # specializations is a JSONField (list), filter by contains
        return queryset.filter(specializations__contains=[value])

    def filter_court(self, queryset, name, value):
        return queryset.filter(courts_practiced__contains=[value])

    def filter_language(self, queryset, name, value):
        return queryset.filter(languages_known__icontains=value)


class PostFilter(django_filters.FilterSet):
    """
    Filters for community feed.
    Usage: /api/feed/?post_type=legal_update
    """
    post_type = django_filters.ChoiceFilter(choices=Post.POST_TYPES)
    author = django_filters.UUIDFilter(field_name='author__id')

    class Meta:
        model = Post
        fields = ['post_type', 'author']


class ChannelFilter(django_filters.FilterSet):
    """
    Filters for channels.
    Usage: /api/channels/?channel_type=court&city=Delhi
    """
    channel_type = django_filters.ChoiceFilter(choices=Channel.CHANNEL_TYPES)
    city = django_filters.CharFilter(lookup_expr='icontains')
    state = django_filters.CharFilter(lookup_expr='icontains')
    is_official = django_filters.BooleanFilter()

    class Meta:
        model = Channel
        fields = ['channel_type', 'city', 'state', 'is_official']