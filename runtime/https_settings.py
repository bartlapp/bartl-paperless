# Paperless 3.3.x has no environment switch for these native Django settings.
# Extend its settings rather than replacing application authentication.
from paperless.settings import *  # noqa: F403

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
