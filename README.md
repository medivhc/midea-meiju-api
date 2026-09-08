# 美的美居智能家居 REST API

不运行美的美居APP，通过HTTP接口即可查询家电状态和控制家电。基于美的美居云API（私有协议逆向）实现，无需申请官方开发者资质。

## 功能特性

- **账号登录**：手机号+密码登录美居账号，Token自动刷新
- **设备发现**：自动获取家庭列表和所有智能设备
- **状态查询**：实时查询设备运行状态（温度、模式、风速等）
- **设备控制**：通用JSON键值对控制，支持所有美居设备
- **空调快捷控制**：语义化空调控制（开关、温度、模式、风速、摆风等）
- **原始透传**：支持发送十六进制原始指令（高级用户）
- **多会话管理**：支持多账号同时在线

## 支持的设备类型

| 类型码 | 设备 | 类型码 | 设备 |
|--------|------|--------|------|
| 0xAC | 空调 | 0xFA | 风扇 |
| 0xA1 | 除湿机 | 0xFD | 加湿器 |
| 0xE2 | 电热水器 | 0x15 | 热水器 |
| 0x13 | 电灯 | 0x17 | 洗衣机 |
| 0x21 | 中央空调网关 | 0x26 | 浴霸 |
| 0x44 | 智能温控器 | 0xB6 | 油烟机 |
| 0xB8 | 扫地机器人 | 0xCA | 冰箱 |
| 0xCE | 新风系统 | 0xDC | 干衣机 |
| 0xE1 | 洗碗机 | 0xE3 | 燃气热水器 |
| 0xEA | 电饭煲 | 0xFB | 电暖器 |
| 0xFC | 空气净化器 | | |

> 理论上所有接入美居APP的设备都可通过通用控制接口操作，具体控制字段需参考各设备的物模型。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python app.py
# 或
uvicorn app:app --host 0.0.0.0 --port 8000
```

启动后访问 `http://localhost:8000/docs` 查看交互式API文档。

### 3. 调用示例

#### 登录

```bash
curl -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"account": "13800138000", "password": "your_password"}'
```

返回：
```json
{
  "success": true,
  "token": "abc123...",
  "account": "13800138000",
  "nickname": "用户昵称",
  "expires_in": 604800
}
```

#### 获取设备列表

```bash
curl http://localhost:8000/api/devices \
  -H "Authorization: Bearer <token>"
```

#### 获取设备状态

```bash
curl http://localhost:8000/api/device/123456789/status \
  -H "Authorization: Bearer <token>"
```

#### 通用控制设备

```bash
curl -X POST http://localhost:8000/api/device/123456789/control \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"control": {"power": 1, "temperature": 26, "mode": 1}}'
```

#### 空调快捷控制

```bash
curl -X POST http://localhost:8000/api/device/123456789/ac \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"power": 1, "temperature": 26, "mode": 1, "fan_speed": 2}'
```

## API 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login` | 登录美居账号 |
| POST | `/api/logout` | 退出登录 |
| GET | `/api/homes` | 获取家庭列表 |
| GET | `/api/devices` | 获取所有设备 |
| GET | `/api/devices/{home_id}` | 获取指定家庭设备 |
| GET | `/api/device/{id}/status` | 获取设备状态 |
| POST | `/api/device/{id}/control` | 通用控制（JSON） |
| POST | `/api/device/{id}/raw` | 原始透传控制 |
| POST | `/api/device/{id}/ac` | 空调快捷控制 |
| GET | `/api/info` | 服务信息 |

## 空调控制参数说明

| 参数 | 类型 | 取值 | 说明 |
|------|------|------|------|
| power | int | 0/1 | 开关 |
| temperature | int | 16-30 | 设定温度(℃) |
| mode | int | 0-5 | 0自动 1制冷 2制热 3除湿 4送风 5节能 |
| fan_speed | int | 0/1/2/3/102 | 0自动 1低 2中 3高 102静音 |
| swing_vertical | int | 0/1 | 上下摆风 |
| swing_horizontal | int | 0/1 | 左右摆风 |
| eco | int | 0/1 | 节能模式 |
| dry | int | 0/1 | 干燥模式 |
| aux_heat | int | 0/1 | 电辅热 |
| sleep | int | 0/1 | 睡眠模式 |
| turbo | int | 0/1 | 强劲模式 |
| screen_display | int | 0/1 | 显示屏 |
| beep | int | 0/1 | 蜂鸣器 |

> 注意：不同型号空调支持的参数可能不同，未传的参数保持当前值不变。

## 技术原理

本项目通过逆向美的美居APP的云API实现，核心流程：

1. **登录认证**：调用 `/v1/user/login/id/get` 获取loginId，再调用 `/mj/user/login` 完成登录，获取accessToken和AES通信密钥
2. **请求签名**：每个请求使用HMAC-SHA256签名，签名内容为 `iot_key + 请求体 + 时间戳随机数`
3. **设备控制**：使用新版Lua API `/mjl/v1/device/lua/control`，直接传递JSON键值对，云端自动转换为设备二进制协议
4. **状态查询**：使用 `/mjl/v1/device/status/lua/get` 查询设备状态

## 安全说明

- 本项目仅用于个人智能家居控制学习和研究
- 账号密码仅用于登录美的官方云服务器，不会上传到任何第三方
- 建议在受信任的网络环境中使用，不要将API服务暴露到公网
- 如需公网访问，请务必添加身份认证和HTTPS

## 致谢

本项目基于以下开源项目的研究成果：
- [midea_auto_cloud](https://github.com/sususweet/midea_auto_cloud) - 美的美居云API核心实现
- [hasscc/meiju](https://github.com/hasscc/meiju) - HomeAssistant美居集成
- [midea-beautiful-air](https://github.com/nbogojevic/midea-beautiful-air) - 美的设备本地控制库

## 免责声明

本项目与美的集团无任何关联，为非官方第三方实现。使用本项目产生的一切后果由使用者自行承担。
