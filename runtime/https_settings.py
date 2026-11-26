# Paperless 3.3.x has no environment switch for these native Django settings.
# Preserve Django's complete native setting namespace, including uppercase
# names beginning with underscores that Python's wildcard import excludes.
from paperless import settings as native_settings

globals().update(
    (name, value) for name, value in vars(native_settings).items() if name.isupper()
)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
