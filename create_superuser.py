from django.contrib.auth import get_user_model
import sys

User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print("Superuser 'admin' created with password 'admin'.")
else:
    print("Superuser already exists.")
