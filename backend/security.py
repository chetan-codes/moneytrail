import base64
import hashlib
import hmac
import json
import time


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def issue(secret, organization, payload, ttl=120):
    claims = {'org': organization, 'expires': int(time.time()) + ttl,
              'digest': hashlib.sha256(canonical(payload)).hexdigest()}
    body = base64.urlsafe_b64encode(canonical(claims)).decode()
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


def validate(token, secret, organization, payload):
    try:
        body, signature = token.split('.')
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        claims = json.loads(base64.urlsafe_b64decode(body))
        return (hmac.compare_digest(signature, expected) and claims['org'] == organization
                and claims['expires'] >= time.time()
                and hmac.compare_digest(claims['digest'], hashlib.sha256(canonical(payload)).hexdigest()))
    except (ValueError, KeyError, TypeError):
        return False
