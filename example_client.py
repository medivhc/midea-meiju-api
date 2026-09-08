#!/usr/bin/env python3
"""
美的美居API - Python客户端使用示例
演示如何直接使用 MideaClient 类控制家电，无需启动HTTP服务。
"""
import sys
import json

# 添加当前目录到路径
sys.path.insert(0, '.')

from midea_client import MideaClient, MideaCloudError, DEVICE_TYPES


def main():
    # ====== 配置你的美居账号 ======
    ACCOUNT = "你的手机号"      # 例如: "13800138000"
    PASSWORD = "你的美居密码"    # 美居APP登录密码
    # ================================

    if ACCOUNT == "你的手机号":
        print("请先在脚本中配置你的美居账号和密码！")
        print("编辑 example_client.py，修改 ACCOUNT 和 PASSWORD 变量。")
        return

    print("=" * 50)
    print("  美的美居API - 客户端示例")
    print("=" * 50)

    # 1. 创建客户端并登录
    print("\n[1] 登录美居账号...")
    client = MideaClient(account=ACCOUNT, password=PASSWORD)
    try:
        if client.login():
            print(f"    登录成功! 用户: {client.nickname}")
        else:
            print("    登录失败，请检查账号密码")
            return
    except MideaCloudError as e:
        print(f"    登录错误: {e}")
        return

    # 2. 获取家庭列表
    print("\n[2] 获取家庭列表...")
    homes = client.list_homes()
    for home_id, home_name in homes.items():
        print(f"    家庭ID={home_id}, 名称={home_name}")

    if not homes:
        print("    未找到家庭")
        return

    # 3. 获取第一个家庭的设备列表
    first_home_id = list(homes.keys())[0]
    print(f"\n[3] 获取家庭 '{homes[first_home_id]}' 的设备列表...")
    devices = client.list_devices(first_home_id)
    for dev_id, dev in devices.items():
        type_name = DEVICE_TYPES.get(dev["type"], "未知")
        online = "在线" if dev["online"] else "离线"
        print(f"    ID={dev_id} | {type_name} | {dev['name']} | {online} | 型号={dev['model']}")

    if not devices:
        print("    未找到设备")
        return

    # 4. 查询第一个设备的状态
    first_dev_id = list(devices.keys())[0]
    first_dev = devices[first_dev_id]
    print(f"\n[4] 查询设备 '{first_dev['name']}' 的状态...")
    try:
        status = client.get_device_status(first_dev_id)
        if status:
            print("    当前状态:")
            for k, v in status.items():
                print(f"      {k}: {v}")
        else:
            print("    无法获取状态（设备可能离线）")
    except MideaCloudError as e:
        print(f"    查询错误: {e}")

    # 5. 控制设备示例（空调）
    if first_dev["type"] == 0xAC:  # 空调
        print(f"\n[5] 空调控制示例...")
        print("    示例: 将空调设为制冷26度")
        try:
            # 先获取当前状态
            current = client.get_device_status(first_dev_id) or {}
            # 控制设备（只传需要修改的参数）
            ok = client.control_device(first_dev_id, {
                "power": 1,
                "temperature": 26,
                "mode": 1,  # 1=制冷
            })
            if ok:
                print("    控制指令发送成功!")
                # 刷新状态
                new_status = client.get_device_status(first_dev_id)
                print(f"    新状态: power={new_status.get('power')}, "
                      f"temperature={new_status.get('temperature')}, "
                      f"mode={new_status.get('mode')}")
            else:
                print("    控制失败")
        except MideaCloudError as e:
            print(f"    控制错误: {e}")

    print("\n" + "=" * 50)
    print("  示例执行完毕")
    print("=" * 50)


if __name__ == "__main__":
    main()
