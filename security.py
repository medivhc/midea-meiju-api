"""
美的美居云API - 加密安全模块
基于 midea_auto_cloud 项目的安全实现，改为同步版本。
"""
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from hashlib import md5, sha256
import hmac


class CloudSecurity:
    """美的云API通用安全类"""

    def __init__(self, login_key, iot_key, hmac_key, fixed_key=None, fixed_iv=None):
        self._login_key = login_key
        self._iot_key = iot_key
        self._hmac_key = hmac_key
        self._aes_key = None
        self._aes_iv = None
        self._fixed_key = format(fixed_key, 'x').encode("ascii") if fixed_key else None
        self._fixed_iv = format(fixed_iv, 'x').encode("ascii") if fixed_iv else None

    def sign(self, data: str, random: str) -> str:
        """请求签名：HMAC-SHA256(hmac_key, iot_key + data + random)"""
        msg = self._iot_key + data + random
        sign = hmac.new(self._hmac_key.encode("ascii"), msg.encode("ascii"), sha256)
        return sign.hexdigest()

    def encrypt_password(self, login_id, data):
        """加密登录密码：SHA256(loginId + SHA256(password) + login_key)"""
        m = sha256()
        m.update(data.encode("ascii"))
        login_hash = login_id + m.hexdigest() + self._login_key
        m = sha256()
        m.update(login_hash.encode("ascii"))
        return m.hexdigest()

    def encrypt_iam_password(self, login_id, data) -> str:
        raise NotImplementedError

    @staticmethod
    def get_deviceid(username):
        """生成设备ID：MD5("Hello, {username}!")前16位"""
        return md5(f"Hello, {username}!".encode("ascii")).digest().hex()[:16]

    def set_aes_keys(self, key, iv):
        if isinstance(key, str):
            key = key.encode("ascii")
        if isinstance(iv, str):
            iv = iv.encode("ascii")
        self._aes_key = key
        self._aes_iv = iv

    def aes_encrypt_with_fixed_key(self, data):
        return self.aes_encrypt(data, self._fixed_key, self._fixed_iv)

    def aes_decrypt_with_fixed_key(self, data):
        return self.aes_decrypt(data, self._fixed_key, self._fixed_iv)

    def aes_encrypt(self, data, key=None, iv=None):
        if key is not None:
            aes_key = key
            aes_iv = iv
        else:
            aes_key = self._aes_key
            aes_iv = self._aes_iv
        if aes_key is None:
            raise ValueError("Encrypt need a key")
        if isinstance(data, str):
            data = bytes.fromhex(data)
        if aes_iv is None:  # ECB
            return AES.new(aes_key, AES.MODE_ECB).encrypt(pad(data, 16))
        else:  # CBC
            return AES.new(aes_key, AES.MODE_CBC, iv=aes_iv).encrypt(pad(data, 16))

    def aes_decrypt(self, data, key=None, iv=None):
        if key is not None:
            aes_key = key
            aes_iv = iv
        else:
            aes_key = self._aes_key
            aes_iv = self._aes_iv
        if aes_key is None:
            raise ValueError("Decrypt need a key")
        if isinstance(data, str):
            data = bytes.fromhex(data)
        if aes_iv is None:  # ECB
            return unpad(AES.new(aes_key, AES.MODE_ECB).decrypt(data), len(aes_key)).decode()
        else:  # CBC
            return unpad(AES.new(aes_key, AES.MODE_CBC, iv=aes_iv).decrypt(data), len(aes_key)).decode()


class MeijuCloudSecurity(CloudSecurity):
    """美的美居专用安全类"""

    def __init__(self, login_key, iot_key, hmac_key):
        super().__init__(login_key, iot_key, hmac_key,
                         fixed_key=10864842703515613082)

    def encrypt_iam_password(self, login_id, data) -> str:
        """iampwd: MD5(MD5(password))"""
        md = md5()
        md.update(data.encode("ascii"))
        md_second = md5()
        md_second.update(md.hexdigest().encode("ascii"))
        return md_second.hexdigest()
