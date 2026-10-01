"""What gunicorn serves: `gunicorn fc.wsgi:app`."""
from .hosted import build

app = build()
