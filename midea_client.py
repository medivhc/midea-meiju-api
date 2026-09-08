"""
美的美居云API客户端
基于 midea_auto_cloud 项目的云实现，改为同步版本（requests）。

支持：
- 手机号+密码登录美居账号
- 获取家庭列表
- 获取设备列表
- 查询设备状态（Lua API）
- 控制设备（Lua API，JSON键值对）
- 原始透传控制（二进制指令）
- Token自动刷新
"""
import json
import time
import datetime
import requests
from secrets import token_hex
from typing import Optional

from security import MeijuCloudSecurity


# 美的美居云配置
MEIJU_CONFIG = {
    "app_key": "46579c15",
    "login_key": "ad0ee21d48a64bf49f4fb583ab76e799",
    "iot_key": bytes.fromhex(format(9795516279659324117647275084689641883661667, 'x')).decode(),
    "hmac_key": bytes.fromhex(format(117390035944627627450677220413733956185864939010425, 'x')).decode(),
    "api_url": "https://mp-prod.smartmidea.net/mas/v5/app/proxy?alias=",
    "app_id": "900",
    "app_version": "8.20.0.2",
}

# Token失效错误码
TOKEN_INVALID_CODES = {40002, 7400}


class MideaCloudError(Exception):
    """美的云API错误"""
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class MideaClient:
    """美的美居云客户端（同步版）"""

    def __init__(self, account: str, password: str, proxy: Optional[str] = None):
        """
        初始化客户端
        :param account: 美居账号（手机号）
        :param password: 美居密码
        :param proxy: 可选代理地址
        """
        self._account = account
        self._password = password
        self._proxy = proxy
        self._config = MEIJU_CONFIG
        self._security = MeijuCloudSecurity(
            login_key=self._config["login_key"],
            iot_key=self._config["iot_key"],
            hmac_key=self._config["hmac_key"],
        )
        self._device_id = MeijuCloudSecurity.get_deviceid(account)
        self._access_token: Optional[str] = None
        self._login_id: Optional[str] = None
        self._nickname: Optional[str] = None
        self._session = requests.Session()
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

    @property
    def is_logged_in(self) -> bool:
        return self._access_token is not None

    @property
    def nickname(self) -> str:
        return self._nickname or self._account

    def _api_request(self, endpoint: str, data: dict, method: str = "POST",
                      _retried: bool = False) -> Optional[dict]:
        """
        通用API请求（带签名、自动重登）
        """
        if not data.get("reqId"):
            data["reqId"] = token_hex(16)
        if not data.get("stamp"):
            data["stamp"] = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        random = str(int(time.time()))
        url = self._config["api_url"] + endpoint
        dump_data = json.dumps(data)
        sign = self._security.sign(dump_data, random)

        headers = {
            "content-type": "application/json; charset=utf-8",
            "secretVersion": "1",
            "sign": sign,
            "random": random,
        }
        if self._access_token:
            headers["accesstoken"] = self._access_token

        is_login_endpoint = "/user/login" in endpoint or "/unitcenter/router/" in endpoint

        try:
            resp = self._session.request(
                method, url, headers=headers, data=dump_data, timeout=30
            )
            response = resp.json()
        except Exception as e:
            raise MideaCloudError(-1, f"请求失败: {e}")

        code = int(response.get("code", -1))

        if code == 0:
            return response.get("data", {"message": "ok"})

        # Token失效，自动重新登录后重试
        if (not _retried and not is_login_endpoint
                and self._is_token_invalid(response)):
            self._access_token = None
            if self.login():
                return self._api_request(endpoint, data, method, _retried=True)
            return None

        msg = response.get("msg") or response.get("message") or "未知错误"
        raise MideaCloudError(code, msg)

    @staticmethod
    def _is_token_invalid(response: dict) -> bool:
        try:
            code = int(response.get("code", -1))
        except Exception:
            code = -1
        msg = str(response.get("msg") or response.get("message") or "").lower()
        return (
            code in TOKEN_INVALID_CODES
            or "user token not exist" in msg
            or "token校验不通过" in msg
        )

    def _get_login_id(self) -> Optional[str]:
        """第一步：获取loginId"""
        data = {
            "loginAccount": self._account,
            "type": "1",
        }
        response = self._api_request("/v1/user/login/id/get", data)
        if response:
            return response.get("loginId")
        return None

    def login(self) -> bool:
        """
        登录美的美居账号
        :return: 是否登录成功
        """
        login_id = self._get_login_id()
        if not login_id:
            return False
        self._login_id = login_id

        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        data = {
            "iotData": {
                "clientType": 1,
                "deviceId": self._device_id,
                "iampwd": self._security.encrypt_iam_password(login_id, self._password),
                "iotAppId": self._config["app_id"],
                "loginAccount": self._account,
                "password": self._security.encrypt_password(login_id, self._password),
                "reqId": token_hex(16),
                "stamp": stamp,
            },
            "data": {
                "appKey": self._config["app_key"],
                "deviceId": self._device_id,
                "platform": 2,
            },
            "timestamp": stamp,
            "stamp": stamp,
        }

        response = self._api_request("/mj/user/login", data)
        if response:
            self._access_token = response["mdata"]["accessToken"]
            # 解密AES密钥
            decrypted_key = self._security.aes_decrypt_with_fixed_key(response["key"])
            self._security.set_aes_keys(decrypted_key, None)
            # 获取用户昵称
            if "userInfo" in response and "nickName" in response["userInfo"]:
                self._nickname = response["userInfo"]["nickName"]
            return True
        return False

    def list_homes(self) -> dict:
        """
        获取家庭列表
        :return: {homegroupId: name}
        """
        response = self._api_request("/v1/homegroup/list/get", {})
        homes = {}
        if response:
            for home in response.get("homeList", []):
                homes[int(home["homegroupId"])] = home["name"]
        return homes

    def list_devices(self, home_id: int) -> dict:
        """
        获取指定家庭下的设备列表
        :param home_id: 家庭ID
        :return: {applianceCode: device_info}
        """
        data = {"homegroupId": home_id}
        response = self._api_request("/v1/appliance/home/list/get", data)
        appliances = {}
        if response:
            for home in response.get("homeList", []):
                for room in home.get("roomList", []):
                    for appliance in room.get("applianceList", []):
                        device_info = {
                            "name": appliance.get("name"),
                            "type": int(appliance.get("type"), 16),
                            "type_hex": appliance.get("type"),
                            "sn": self._security.aes_decrypt(appliance["sn"]) if appliance.get("sn") else "",
                            "sn8": appliance.get("sn8", "00000000"),
                            "category": appliance.get("category"),
                            "smart_product_id": appliance.get("smartProductId", "0"),
                            "model_number": appliance.get("modelNumber", "0"),
                            "manufacturer_code": appliance.get("enterpriseCode", "0000"),
                            "model": appliance.get("productModel") or appliance.get("sn8"),
                            "online": appliance.get("onlineStatus") == "1",
                            "room_name": room.get("name"),
                        }
                        appliances[int(appliance["applianceCode"])] = device_info
        return appliances

    def get_device_status(self, appliance_code: int, query: Optional[dict] = None) -> Optional[dict]:
        """
        查询设备状态（Lua API）
        :param appliance_code: 设备ID
        :param query: 查询参数，空字典{}获取全部状态
        :return: 设备状态字典
        """
        if query is None:
            query = {}
        data = {
            "applianceCode": str(appliance_code),
            "command": {"query": query},
        }
        return self._api_request("/mjl/v1/device/status/lua/get", data)

    def control_device(self, appliance_code: int, control: dict,
                       status: Optional[dict] = None) -> bool:
        """
        控制设备（Lua API，JSON键值对）
        :param appliance_code: 设备ID
        :param control: 控制参数，如 {"power": 1, "temperature": 26}
        :param status: 可选，当前状态（部分设备需要）
        :return: 是否成功
        """
        data = {
            "applianceCode": str(appliance_code),
            "command": {"control": control},
        }
        if status:
            data["command"]["status"] = status
        response = self._api_request("/mjl/v1/device/lua/control", data)
        return response is not None

    def send_raw_command(self, appliance_code: int, cmd_hex: str) -> Optional[str]:
        """
        发送原始透传控制指令（二进制）
        :param appliance_code: 设备ID
        :param cmd_hex: 十六进制指令字符串
        :return: 响应数据（十进制字符串），失败返回None
        """
        params = {
            "applianceCode": str(appliance_code),
            "order": self._security.aes_encrypt(bytes.fromhex(cmd_hex)).hex(),
            "timestamp": "true",
            "isFull": "false",
        }
        response = self._api_request("/v1/appliance/transparent/send", params)
        if response and response.get("reply"):
            reply_data = self._security.aes_decrypt(bytes.fromhex(response["reply"]))
            return reply_data
        return None

    def export_session(self) -> dict:
        """导出会话信息，用于持久化"""
        return {
            "account": self._account,
            "access_token": self._access_token,
            "aes_key": self._security._aes_key.decode("ascii") if self._security._aes_key else None,
            "device_id": self._device_id,
            "nickname": self._nickname,
        }

    def import_session(self, session_data: dict):
        """导入会话信息，跳过登录"""
        self._access_token = session_data.get("access_token")
        aes_key = session_data.get("aes_key")
        if aes_key:
            self._security._aes_key = aes_key.encode("ascii")
            self._security._aes_iv = None
        self._nickname = session_data.get("nickname")


# 设备类型映射表（常用）
DEVICE_TYPES = {
    0xAC: "空调",
    0xFA: "风扇",
    0xA1: "除湿机",
    0xFD: "加湿器",
    0xE2: "电热水器",
    0x15: "热水器",
    0x3D: "热水器",
    0x13: "电灯",
    0x17: "洗衣机",
    0x21: "中央空调网关",
    0x26: "浴霸",
    0x44: "智能温控器",
    0xB6: "油烟机",
    0xB8: "扫地机器人",
    0xCA: "冰箱",
    0xCE: "新风系统",
    0xDC: "干衣机",
    0xE1: "洗碗机",
    0xE3: "恒温燃气热水器",
    0xEA: "电饭煲",
    0xFB: "电暖器",
    0xFC: "空气净化器",
}
