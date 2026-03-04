import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app_ela.settings')
django.setup()

from django.db import connection

try:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM django_migrations WHERE app='core' AND name LIKE '0004_%';")
        print("Registros antigos de migração apagados do banco de dados!")
except Exception as e:
    print(f"Erro ao limpar migrações: {e}")
