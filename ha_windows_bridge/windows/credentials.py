"""Windows user-bound encryption; no credentials are logged."""
class DpapiCipher:
    def encrypt(self, plaintext: bytes) -> bytes:
        import win32crypt
        return win32crypt.CryptProtectData(plaintext, "HA Windows Bridge 2.0", None, None, None, 0)

    def decrypt(self, ciphertext: bytes) -> bytes:
        import win32crypt
        return win32crypt.CryptUnprotectData(ciphertext, None, None, None, 0)[1]
