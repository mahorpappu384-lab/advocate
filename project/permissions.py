from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwnerOrReadOnly(BasePermission):
    """Object-level: owner can write, others can only read."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj == request.user or getattr(obj, 'user', None) == request.user


class IsVerifiedAdvocate(BasePermission):
    """Only verified advocates with approved status can access."""
    message = "Your advocate verification is pending or rejected."

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_advocate and
            request.user.advocate_status == 'approved'
        )


class IsAdminOrReadOnly(BasePermission):
    """Admins can write; authenticated users can read."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return request.user and request.user.is_staff


class IsChannelAdmin(BasePermission):
    """Only channel admins/moderators can manage channels."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        from api.models import ChannelMembership
        return ChannelMembership.objects.filter(
            channel=obj,
            user=request.user,
            role__in=['admin', 'moderator']
        ).exists()


class IsMessageOwner(BasePermission):
    """Only message sender can edit/delete their message."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.sender == request.user


class IsGroupMember(BasePermission):
    """Only group members can access group resources."""
    def has_object_permission(self, request, view, obj):
        from api.models import GroupMembership
        return GroupMembership.objects.filter(
            group=obj, user=request.user
        ).exists()