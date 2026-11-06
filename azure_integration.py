import re
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs

class ValidationError(ValueError):
    pass

def available():
    try:
        import azure.storage.blob
        return True
    except ImportError:
        return False

def operate(account, container, token, photo=None):
    if not re.fullmatch(r'[a-z0-9]{3,24}', account) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]', container):
        raise ValidationError('Invalid storage account or container name.')
    params = parse_qs(token.lstrip('?'))
    try:
        expiry = datetime.fromisoformat(params['se'][0].replace('Z','+00:00'))
        remaining = expiry - datetime.now(timezone.utc)
        permissions = params['sp'][0]
        valid = timedelta(0) < remaining <= timedelta(hours=24) and params.get('sr') == ['c'] and params.get('spr') == ['https'] and set(permissions) <= set('rcw') and bool(params.get('sig'))
        valid = valid and 'r' in permissions and (bool(set(permissions) & set('cw')) if photo else True)
        if not valid:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise ValidationError('Use an HTTPS container SAS expiring within 24 hours: read for testing, read plus create/write for copying; no delete/list permissions.') from None
    from azure.storage.blob import ContainerClient, ContentSettings
    # Never persist tokens, URLs with SAS, SDK exceptions, or connection objects.
    with ContainerClient(account_url=f'https://{account}.blob.core.windows.net', container_name=container, credential=token.lstrip('?'), connection_timeout=5, read_timeout=10, retry_total=0) as client:
        props = client.get_container_properties(timeout=10)
        if props.get('public_access'):
            raise ValidationError('Use a private container.')
        if photo:
            with open(photo,'rb') as stream:
                client.upload_blob(name=photo.name, data=stream, overwrite=False, content_settings=ContentSettings(content_type='image/jpeg'), timeout=10)
