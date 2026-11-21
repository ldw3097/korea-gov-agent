"""Validate the signed Access assertion, never identity headers alone."""
import jwt


class AccessVerifier:
    def __init__(self, issuer: str, audience: str):
        self.issuer = issuer
        self.audience = audience
        self.keys = jwt.PyJWKClient(issuer + '/cdn-cgi/access/certs', timeout=5)

    def verify(self, token: str) -> dict:
        if not token or len(token) > 16384:
            raise ValueError('Missing or oversized assertion')
        key = self.keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=self.audience,
                            issuer=self.issuer, options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'email']})
        if not isinstance(claims['sub'], str) or not claims['sub'] or len(claims['sub']) > 256:
            raise ValueError('Invalid subject')
        email = claims['email']
        if not isinstance(email, str) or not 3 <= len(email) <= 100 or '@' not in email:
            raise ValueError('Invalid email')
        claims['email'] = email.casefold()
        return claims
