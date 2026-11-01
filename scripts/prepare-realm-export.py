import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

source = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else ROOT / '.local/keycloak-results-export.raw.json'
)

destination = (
    Path(sys.argv[2])
    if len(sys.argv) > 2
    else ROOT / 'keycloak/keycloak-results-export.json'
)

realm = json.loads(source.read_text(encoding='utf-8-sig'))


# Секреты клиентов.
for client in realm.get('clients', []):
    if client.get('clientId') == 'bionicpro-auth':
        client['secret'] = '${BIONICPRO_AUTH_CLIENT_SECRET}'

    elif client.get('bearerOnly'):
        # Bearer-only клиент проверяет токены и не использует client secret.
        client.pop('secret', None)

    elif client.get('secret') and not client['secret'].startswith('${'):
        raise SystemExit(
            'Обнаружен дополнительный confidential-клиент. '
            'Для него нужно определить переменную секрета. '
            'Экспорт не записан.'
        )


# Настройки Яндекс ID.
for provider in realm.get('identityProviders', []):
    if provider.get('alias') == 'yandex':
        provider.setdefault('config', {}).update(
            clientId='${YANDEX_CLIENT_ID}',
            clientSecret='${YANDEX_CLIENT_SECRET}'
        )

    elif provider.get('config', {}).get('clientSecret'):
        raise SystemExit(
            'Обнаружен дополнительный Identity Provider с секретом. '
            'Для него нужно определить переменную окружения. '
            'Экспорт не записан.'
        )


# Пароль подключения к LDAP.
def clean_components(groups):
    for components in groups.values():
        for component in components:
            if component.get('providerId') == 'ldap':
                component.setdefault('config', {})['bindCredential'] = [
                    '${LDAP_ADMIN_PASSWORD}'
                ]

            clean_components(component.get('subComponents', {}))


clean_components(realm.get('components', {}))


# Удаляем персональные OTP-секреты из экспортируемой копии.
removed = 0

for user in realm.get('users', []):
    credentials = user.get('credentials', [])
    count = sum(
        credential.get('type') == 'otp'
        for credential in credentials
    )

    if count:
        user['credentials'] = [
            credential
            for credential in credentials
            if credential.get('type') != 'otp'
        ]

        actions = user.setdefault('requiredActions', [])

        if 'CONFIGURE_TOTP' not in actions:
            actions.append('CONFIGURE_TOTP')

        removed += count

    # Удаляем сохранённые токены внешних провайдеров, если они попали в экспорт.
    for identity in user.get('federatedIdentities', []):
        identity.pop('token', None)


destination.parent.mkdir(parents=True, exist_ok=True)

destination.write_text(
    json.dumps(realm, ensure_ascii=False, indent=2) + '\n',
    encoding='utf-8'
)

print('Сохранено:', destination)
print('Удалено OTP-credentials из экспорта:', removed)
print('Работающий Keycloak и аутентификаторы пользователей не изменены.')