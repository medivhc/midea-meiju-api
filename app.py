"""
美的美居智能家居 REST API 服务
基于 FastAPI 构建，提供不运行美居APP即可查询和控制家电的HTTP接口。

启动方式：
    uvicorn app:app --host 0.0.0.0 --port 8000

接口概览：
    POST   /api/login              登录美居账号
    POST   /api/logout             退出登录
    GET    /api/homes              获取家庭列表
    GET    /api/devices            获取设备列表（所有家庭）
    GET    /api/devices/{home_id}  获取指定家庭的设备列表
    GET    /api/device/{id}/status 获取设备状态
    POST   /api/device/{id}/control 通用控制设备（JSON键值对）
    POST   /api/device/{id}/raw    原始透传控制（十六进制指令）
    POST   /api/device/{id}/ac     空调快捷控制
"""
import time
import uuid
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from midea_client import MideaClient, MideaCloudError, DEVICE_TYPES


# ============================================================
# 会话管理
# ============================================================
class SessionManager:
    """内存会话管理器（生产环境可替换为Redis）"""

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._ttl = 7 * 24 * 3600  # 7天

    def create(self, client: MideaClient) -> str:
        token = uuid.uuid4().hex
        self._sessions[token] = {
            "client": client,
            "created_at": time.time(),
            "account": client._account,
        }
        return token

    def get(self, token: str) -> Optional[MideaClient]:
        session = self._sessions.get(token)
        if not session:
            return None
        if time.time() - session["created_at"] > self._ttl:
            del self._sessions[token]
            return None
        return session["client"]

    def remove(self, token: str):
        self._sessions.pop(token, None)

    def list_sessions(self) -> list:
        return [
            {"token": k[:8] + "...", "account": v["account"],
             "created_at": v["created_at"]}
            for k, v in self._sessions.items()
        ]


session_manager = SessionManager()


def get_client(authorization: str = Header(...)) -> MideaClient:
    """依赖注入：从Authorization头获取会话客户端"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的Authorization格式")
    token = authorization[7:]
    client = session_manager.get(token)
    if not client:
        raise HTTPException(status_code=401, detail="会话已过期或不存在，请重新登录")
    return client


# ============================================================
# 请求/响应模型
# ============================================================
class LoginRequest(BaseModel):
    account: str = Field(..., description="美居账号（手机号）")
    password: str = Field(..., description="美居密码")


class ControlRequest(BaseModel):
    control: Dict[str, Any] = Field(..., description="控制参数键值对，如 {\"power\": 1, \"temperature\": 26}")
    status: Optional[Dict[str, Any]] = Field(None, description="可选，当前状态快照")


class RawCommandRequest(BaseModel):
    command: str = Field(..., description="十六进制指令字符串，如 \"AA 0B AC 00 00 00 00 00 03 01 01\"")


class ACControlRequest(BaseModel):
    """空调快捷控制参数"""
    power: Optional[int] = Field(None, ge=0, le=1, description="开关：0关 1开")
    temperature: Optional[int] = Field(None, ge=16, le=30, description="设定温度(℃)")
    mode: Optional[int] = Field(None, ge=0, le=5, description="模式：0自动 1制冷 2制热 3除湿 4送风 5节能")
    fan_speed: Optional[int] = Field(None, ge=0, le=100, description="风速：0自动 1低 2中 3高 102静音")
    swing_vertical: Optional[int] = Field(None, ge=0, le=1, description="上下摆风：0关 1开")
    swing_horizontal: Optional[int] = Field(None, ge=0, le=1, description="左右摆风：0关 1开")
    eco: Optional[int] = Field(None, ge=0, le=1, description="节能模式：0关 1开")
    dry: Optional[int] = Field(None, ge=0, le=1, description="干燥模式：0关 1开")
    aux_heat: Optional[int] = Field(None, ge=0, le=1, description="电辅热：0关 1开")
    sleep: Optional[int] = Field(None, ge=0, le=1, description="睡眠模式：0关 1开")
    turbo: Optional[int] = Field(None, ge=0, le=1, description="强劲模式：0关 1开")
    screen_display: Optional[int] = Field(None, ge=0, le=1, description="显示屏：0关 1开")
    beep: Optional[int] = Field(None, ge=0, le=1, description="蜂鸣器：0关 1开")


# ============================================================
# FastAPI 应用
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("  美的美居智能家居 API 服务已启动")
    print("  文档地址: http://localhost:8000/docs")
    print("=" * 60)
    yield
    print("服务已停止")


app = FastAPI(
    title="美的美居智能家居 API",
    description="不运行美居APP，通过HTTP接口查询家电状态和控制家电。基于美的美居云API实现。",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================
# 认证接口
# ============================================================
@app.post("/api/login", summary="登录美居账号")
def login(req: LoginRequest):
    """
    使用美的美居账号（手机号+密码）登录，返回会话token。
    后续请求需在Header中携带 `Authorization: Bearer <token>`。
    """
    try:
        client = MideaClient(account=req.account, password=req.password)
        if not client.login():
            raise HTTPException(status_code=401, detail="登录失败，请检查账号密码")
        token = session_manager.create(client)
        return {
            "success": True,
            "token": token,
            "account": req.account,
            "nickname": client.nickname,
            "expires_in": session_manager._ttl,
        }
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=f"美的云API错误: {e.message}")


@app.post("/api/logout", summary="退出登录")
def logout(authorization: str = Header(...)):
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    session_manager.remove(token)
    return {"success": True, "message": "已退出登录"}


# ============================================================
# 家庭与设备接口
# ============================================================
@app.get("/api/homes", summary="获取家庭列表")
def get_homes(client: MideaClient = Depends(get_client)):
    """获取当前账号下的所有家庭"""
    try:
        homes = client.list_homes()
        return {
            "success": True,
            "homes": [{"id": k, "name": v} for k, v in homes.items()],
        }
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/devices", summary="获取所有设备列表")
def get_all_devices(client: MideaClient = Depends(get_client)):
    """获取所有家庭下的全部设备"""
    try:
        homes = client.list_homes()
        all_devices = []
        for home_id, home_name in homes.items():
            devices = client.list_devices(home_id)
            for dev_id, dev in devices.items():
                dev["id"] = dev_id
                dev["home_id"] = home_id
                dev["home_name"] = home_name
                dev["type_name"] = DEVICE_TYPES.get(dev["type"], "未知设备")
                all_devices.append(dev)
        return {"success": True, "count": len(all_devices), "devices": all_devices}
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/devices/{home_id}", summary="获取指定家庭的设备列表")
def get_devices(home_id: int, client: MideaClient = Depends(get_client)):
    """获取指定家庭ID下的设备列表"""
    try:
        devices = client.list_devices(home_id)
        result = []
        for dev_id, dev in devices.items():
            dev["id"] = dev_id
            dev["type_name"] = DEVICE_TYPES.get(dev["type"], "未知设备")
            result.append(dev)
        return {"success": True, "home_id": home_id, "count": len(result), "devices": result}
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ============================================================
# 设备状态与控制接口
# ============================================================
@app.get("/api/device/{device_id}/status", summary="获取设备状态")
def get_device_status(device_id: int, client: MideaClient = Depends(get_client)):
    """
    查询设备当前状态。
    返回的字段因设备类型而异，空调通常包含 power、temperature、mode、fan_speed 等。
    """
    try:
        status = client.get_device_status(device_id)
        if status is None:
            raise HTTPException(status_code=404, detail="无法获取设备状态，设备可能离线")
        return {"success": True, "device_id": device_id, "status": status}
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/device/{device_id}/control", summary="通用控制设备")
def control_device(device_id: int, req: ControlRequest,
                   client: MideaClient = Depends(get_client)):
    """
    通用设备控制接口，使用JSON键值对控制设备。
    控制参数因设备类型而异，例如：
    - 空调: {\"power\": 1, \"temperature\": 26, \"mode\": 1}
    - 风扇: {\"power\": 1, \"wind_speed\": 2}
    - 灯: {\"power\": 1, \"brightness\": 80}
    """
    try:
        ok = client.control_device(device_id, req.control, req.status)
        if not ok:
            raise HTTPException(status_code=400, detail="控制指令发送失败")
        # 控制后自动刷新状态
        status = client.get_device_status(device_id)
        return {"success": True, "device_id": device_id, "control": req.control, "current_status": status}
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/device/{device_id}/raw", summary="原始透传控制")
def raw_control(device_id: int, req: RawCommandRequest,
                client: MideaClient = Depends(get_client)):
    """
    发送原始二进制透传指令（高级用户）。
    command为十六进制字符串，空格可省略。
    例如空调查询指令: \"AA 0B AC 00 00 00 00 00 03 01 01\"
    """
    try:
        cmd_hex = req.command.replace(" ", "").replace("\n", "")
        reply = client.send_raw_command(device_id, cmd_hex)
        return {
            "success": reply is not None,
            "device_id": device_id,
            "command_sent": cmd_hex,
            "reply": reply,
        }
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ============================================================
# 空调快捷控制
# ============================================================
@app.post("/api/device/{device_id}/ac", summary="空调快捷控制")
def ac_control(device_id: int, req: ACControlRequest,
               client: MideaClient = Depends(get_client)):
    """
    空调快捷控制接口，提供常用空调参数的语义化控制。
    只传需要修改的参数即可，未传的参数保持不变。
    """
    control = {}
    if req.power is not None:
        control["power"] = req.power
    if req.temperature is not None:
        control["temperature"] = req.temperature
    if req.mode is not None:
        control["mode"] = req.mode
    if req.fan_speed is not None:
        control["fan_speed"] = req.fan_speed
    if req.swing_vertical is not None:
        control["swing_vertical"] = req.swing_vertical
    if req.swing_horizontal is not None:
        control["swing_horizontal"] = req.swing_horizontal
    if req.eco is not None:
        control["eco"] = req.eco
    if req.dry is not None:
        control["dry"] = req.dry
    if req.aux_heat is not None:
        control["aux_heat"] = req.aux_heat
    if req.sleep is not None:
        control["sleep"] = req.sleep
    if req.turbo is not None:
        control["turbo"] = req.turbo
    if req.screen_display is not None:
        control["screen_display"] = req.screen_display
    if req.beep is not None:
        control["beep"] = req.beep

    if not control:
        raise HTTPException(status_code=400, detail="至少提供一个控制参数")

    try:
        ok = client.control_device(device_id, control)
        if not ok:
            raise HTTPException(status_code=400, detail="空调控制失败")
        status = client.get_device_status(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "control_sent": control,
            "current_status": status,
        }
    except MideaCloudError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ============================================================
# 系统信息
# ============================================================
@app.get("/api/info", summary="服务信息")
def service_info():
    """获取服务基本信息和支持的设备类型"""
    return {
        "service": "美的美居智能家居 API",
        "version": "1.0.0",
        "active_sessions": len(session_manager._sessions),
        "supported_device_types": {f"0x{k:02X}": v for k, v in DEVICE_TYPES.items()},
    }


@app.get("/", summary="根路径")
def root():
    return {
        "name": "美的美居智能家居 API",
        "docs": "/docs",
        "login": "POST /api/login",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
