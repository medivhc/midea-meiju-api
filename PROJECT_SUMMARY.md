# 美的美居智能家居 API 项目总结

> 项目周期：2026-09-08
> 目标：不运行美的美居APP，通过HTTP接口查询家电状态和控制家电

---

## 一、项目背景

### 1.1 需求来源

用户拥有美的智能家电（空调、破壁机等），日常通过「美的美居」APP管理。希望实现：

- **不启动APP**即可获取家电实时运行状态
- 通过程序化方式（API调用）控制家电
- 生成可被其他系统/脚本调用的标准HTTP接口

### 1.2 可选技术路线

调研后发现存在三条技术路线：

| 路线 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| **官方开放平台** | 美的IoT开发者平台云云对接（OAuth2） | 官方支持、稳定 | 需申请开发者资质、审核流程、企业级对接 |
| **局域网直连** | 设备本地UDP/TCP协议（V1/V2/V3） | 不依赖云端、延迟低 | 需与设备同局域网、需获取设备token/key、V3设备加密复杂 |
| **私有云API** | 逆向美居APP的云接口，直接用账号密码调用 | 无需资质、跨网络、功能完整 | 非官方、协议可能变更 |

**最终选择：私有云API路线** —— 无需申请官方开发者，直接用美居账号密码登录云端，兼顾易用性和功能完整性。

---

## 二、技术调研过程

### 2.1 信息搜集

通过并行搜索，定位到以下关键资源：

1. **美的IoT官方开发者平台** (`iot.midea.com`)
   - 提供v1/v2/v3三版云云对接API文档
   - 核心接口：OAuth2授权、设备列表、设备控制、物模型action
   - API域名：`api-prod.smartmidea.net`

2. **关键开源项目**
   - `sususweet/midea_auto_cloud` —— 最活跃的美居云API实现（500+ commits，35个release），支持50+设备类型
   - `hasscc/meiju` —— HomeAssistant美居集成，使用美居自带云API
   - `nbogojevic/midea-beautiful-air` —— 本地+云端控制库，PyPI可安装
   - `georgezhao2010/midea_ac_lan` —— 局域网直连HA集成
   - `tooplick/nekro_midea_plugin` —— 提供REST API的美居控制插件
   - `barban-dev/midea_inventor_dehumidifier` —— 早期逆向成果，文档详尽

### 2.2 核心代码分析

深入阅读 `midea_auto_cloud` 项目的核心模块（共3376行）：

| 文件 | 行数 | 作用 |
|------|------|------|
| `core/cloud.py` | 1347 | 云API客户端：登录、签名、请求、设备列表、状态查询、控制 |
| `core/security.py` | 243 | 加密安全：HMAC签名、AES加解密、密码加密 |
| `core/device.py` | 831 | 设备抽象：状态刷新、指令发送、Lua编解码 |
| `core/packet_builder.py` | 59 | 二进制数据包构建（5A5A协议头） |
| `core/message.py` | 158 | 消息帧封装（AA协议头、校验和） |

### 2.3 关键技术发现

#### （1）美居云API基础配置

```
API基础URL: https://mp-prod.smartmidea.net/mas/v5/app/proxy?alias=
app_key:    46579c15
login_key:  ad0ee21d48a64bf49f4fb583ab76e799
APP_ID:     900
APP版本:    8.20.0.2
```

#### （2）登录流程（两步）

```
第一步: POST /v1/user/login/id/get
  参数: {loginAccount: 手机号, type: "1"}
  返回: loginId（会话级登录标识）

第二步: POST /mj/user/login
  参数:
    iotData: {
      clientType: 1,
      deviceId: MD5("Hello, {手机号}!")前16位,
      iampwd: MD5(MD5(密码)),
      iotAppId: "900",
      loginAccount: 手机号,
      password: SHA256(loginId + SHA256(密码) + login_key),
      reqId: 随机32位hex,
      stamp: 时间戳
    }
    data: {appKey, deviceId, platform: 2}
  返回: mdata.accessToken + key（AES加密的通信密钥）
```

#### （3）请求签名机制

每个API请求都需要在Header中携带签名：

```
sign = HMAC-SHA256(hmac_key, iot_key + JSON请求体 + random时间戳)
Header: {
  content-type: application/json; charset=utf-8,
  secretVersion: "1",
  sign: <签名结果>,
  random: <Unix时间戳>,
  accesstoken: <登录后获取>
}
```

#### （4）两种设备控制方式

| 方式 | 接口 | 特点 |
|------|------|------|
| **Lua API（新版）** | `/mjl/v1/device/lua/control` | 直接传JSON键值对，如 `{"power":1,"temperature":26}`，云端自动转换为设备二进制协议 |
| **透传API（旧版）** | `/v1/appliance/transparent/send` | 需手动构建二进制指令帧，AES加密后以hex字符串发送，灵活但复杂 |

状态查询同理：`/mjl/v1/device/status/lua/get`（Lua方式，推荐）。

#### （5）设备类型编码

美的设备以16进制type区分，已识别22种常用类型：
- `0xAC` 空调、`0xFA` 风扇、`0xA1` 除湿机、`0xFD` 加湿器
- `0xE2` 电热水器、`0x13` 电灯、`0x17` 洗衣机、`0xCA` 冰箱
- `0xB8` 扫地机器人、`0xCE` 新风系统、`0xFC` 空气净化器……

---

## 三、项目实现

### 3.1 项目结构

```
midea_api/
├── app.py              # FastAPI REST服务（361行，11个接口）
├── midea_client.py     # 美的云客户端核心（337行）
├── security.py         # 加密安全模块（106行）
├── example_client.py   # Python直接调用示例（112行）
├── requirements.txt    # 依赖清单
└── README.md           # 使用文档
```

### 3.2 核心模块设计

#### security.py — 加密安全层

- `CloudSecurity` 基类：HMAC-SHA256签名、AES-ECB/CBC加解密、SHA256密码加密
- `MeijuCloudSecurity` 美居专属：MD5(MD5()) iampwd、固定密钥解密AES通信密钥
- 设备ID生成：`MD5("Hello, {username}!")` 前16位

#### midea_client.py — 云客户端

- `MideaClient` 类封装完整云交互
- 自动Token刷新：检测到 `40002 user token not exist` 时自动重新登录并重试
- 会话导入/导出：支持持久化accessToken和AES密钥，避免重复登录
- 方法：`login()`、`list_homes()`、`list_devices()`、`get_device_status()`、`control_device()`、`send_raw_command()`

#### app.py — REST API层

- 基于FastAPI，自动生成OpenAPI文档（`/docs`）
- 内存会话管理器：登录返回Bearer Token，7天有效期
- 依赖注入：`get_client()` 从Authorization头解析会话
- Pydantic请求模型：空调控制14个参数带范围校验

### 3.3 API接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login` | 登录美居账号 |
| POST | `/api/logout` | 退出登录 |
| GET | `/api/homes` | 获取家庭列表 |
| GET | `/api/devices` | 获取所有设备 |
| GET | `/api/devices/{home_id}` | 指定家庭设备 |
| GET | `/api/device/{id}/status` | 设备实时状态 |
| POST | `/api/device/{id}/control` | 通用JSON控制 |
| POST | `/api/device/{id}/raw` | 原始透传控制 |
| POST | `/api/device/{id}/ac` | 空调快捷控制 |
| GET | `/api/info` | 服务信息 |
| GET | `/` | 根路径 |

### 3.4 空调快捷控制参数

支持14个语义化参数：power、temperature(16-30)、mode(0-5)、fan_speed、swing_vertical/horizontal、eco、dry、aux_heat、sleep、turbo、screen_display、beep。

---

## 四、实际验证结果

使用用户真实账号（手机号 185****0885）完成端到端测试：

### 4.1 登录认证

- 登录成功，获取昵称 `0885`
- accessToken和AES通信密钥正常获取
- 设备ID生成正确

### 4.2 设备发现

- 家庭：1个（`0885的家`，ID=76963797）
- 设备：2台

| 设备 | 类型 | 在线 | 位置 | 型号 |
|------|------|------|------|------|
| 壁挂式空调 | 0xAC | 是 | 卧室 | KFR-26G/BDN8Y-PH400(3)A |
| 破壁机 | 0xF1 | 否 | 厨房 | MJ-PB80W3-300 |

### 4.3 状态查询

空调状态查询成功返回 **30+个字段**，包括：

- 电源：off（关闭）
- 模式：cool（制冷）
- 设定温度：26℃
- 室内温度：27℃
- 风速：102（静音）
- 摆风、ECO、干燥、电辅热、睡眠、强劲等全部可读取
- 滤网使用时长、故障码、PMV舒适度指数等高级字段

### 4.4 验证结论

- 登录认证流程 ✅
- 家庭/设备列表获取 ✅
- 设备在线状态判断 ✅
- 实时状态查询（Lua API）✅
- 加密/签名/解密全链路 ✅
- Token自动刷新机制（代码级验证）✅

---

## 五、学到的东西

### 5.1 智能家居云API逆向方法论

1. **从开源项目入手**：不要从零抓包，先找已有的HA集成、Python库等开源项目，站在巨人肩膀上
2. **定位核心配置**：app_key、login_key、API域名是逆向的"钥匙"，通常在constants或cloud配置中
3. **拆解登录流程**：登录是最复杂的环节，通常分多步（获取loginId → 加密密码 → 换取token），密码加密往往是多层hash组合
4. **理解签名机制**：云API普遍用HMAC签名防篡改，需搞清签名原文的拼接顺序（key + body + random）
5. **区分新旧API**：一个APP可能同时存在旧版透传API和新版物模型/Lua API，优先用新版（JSON化、更简单）

### 5.2 美的IoT技术架构认知

- **三层架构**：设备层（二进制5A5A/8370协议）→ 接入层（云端MQTT/长连接）→ 应用层（REST API）
- **两种控制路径**：
  - 云端路径：APP → 美居云 → 设备（延迟高、跨网络、需在线）
  - 本地路径：APP → 局域网UDP/TCP → 设备（延迟低、V3需token+key握手）
- **物模型演进**：从早期二进制透传 → Lua脚本适配 → 标准物模型（Thing Model），控制方式逐渐JSON化
- **安全设计**：登录密码双层hash、通信AES加密、请求HMAC签名、设备级token/key，层层设防

### 5.3 工程实践收获

- **FastAPI构建API服务**：依赖注入、Pydantic模型校验、自动OpenAPI文档、异步支持
- **会话管理设计**：Token-based认证、内存会话存储、TTL过期、自动重登
- **加密库使用**：pycryptodome的AES-ECB/CBC模式、PKCS7填充、HMAC-SHA256
- **代码可维护性**：将加密层、客户端层、API层分离，每层职责单一
- **错误处理**：区分网络错误、业务错误码、Token失效，针对性重试或上报

### 5.4 局限性与后续方向

- **控制功能未实测**：状态查询已验证，设备控制（空调开关/调温）尚未用真实设备执行
- **破壁机类型未适配**：0xF1类型不在已知映射表中，通用控制接口仍可尝试
- **会话持久化**：当前为内存存储，重启后需重新登录，可扩展为文件/Redis持久化
- **设备控制字段**：不同型号空调的控制字段名可能有差异，需根据状态返回的字段名对应控制
- **公网部署安全**：当前无额外认证，公网部署需添加API Key、HTTPS、速率限制

---

## 六、参考资源

- [midea_auto_cloud](https://github.com/sususweet/midea_auto_cloud) —— 核心参考实现
- [hasscc/meiju](https://github.com/hasscc/meiju) —— HA美居集成
- [midea-beautiful-air](https://github.com/nbogojevic/midea-beautiful-air) —— 本地+云端控制库
- [美的IoT开发者平台](https://iot.midea.com/) —— 官方API文档
- [barban-dev/midea_inventor_dehumidifier](https://github.com/barban-dev/midea_inventor_dehumidifier) —— 早期逆向文档
