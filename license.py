"""
License Manager
===============
机器码生成 + 激活码验证。
用于闲鱼销售版本的硬件锁定。
"""

import hashlib
import base64
import os
import json
import uuid
import logging

logger = logging.getLogger("license")

# 嵌入密钥（发布前修改此值，越长越好）
_SECRET = "XiaoYouTV-2026-iptv-v1"

# 激活状态文件
_LICENSE_FILE = "activated.json"


def get_machine_code() -> str:
    """生成机器码：基于 MAC 地址，8 位大写。"""
    mac = uuid.getnode()
    mac_hex = f"{mac:012x}"
    h = hashlib.sha256(mac_hex.encode()).hexdigest()[:8].upper()
    # 格式化为 XXXX-XXXX
    return f"{h[:4]}-{h[4:]}"


def generate_activation_code(machine_code: str) -> str:
    """（卖家工具）根据机器码生成激活码。"""
    clean = machine_code.replace("-", "").upper()
    raw = f"{clean}:{_SECRET}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
    # 格式化为 XXXX-XXXX-XXXX
    return f"{h[:4]}-{h[4:8]}-{h[8:]}"


def verify_activation_code(machine_code: str, activation_code: str) -> bool:
    """验证激活码是否匹配当前机器。"""
    expected = generate_activation_code(machine_code)
    clean_input = activation_code.replace("-", "").upper().strip()
    clean_expected = expected.replace("-", "").upper()
    return clean_input == clean_expected


def is_activated() -> bool:
    """检查当前机器是否已激活。"""
    if not os.path.exists(_LICENSE_FILE):
        return False
    try:
        with open(_LICENSE_FILE, "r") as f:
            data = json.load(f)
        saved_code = data.get("machine_code", "")
        saved_activation = data.get("activation_code", "")
        current_code = get_machine_code()
        if saved_code != current_code:
            return False
        return verify_activation_code(current_code, saved_activation)
    except Exception:
        return False


def save_activation(activation_code: str) -> bool:
    """保存激活状态。成功返回 True。"""
    machine_code = get_machine_code()
    if not verify_activation_code(machine_code, activation_code):
        return False
    data = {
        "machine_code": machine_code,
        "activation_code": activation_code,
    }
    try:
        with open(_LICENSE_FILE, "w") as f:
            json.dump(data, f)
        logger.info("Activation successful")
        return True
    except Exception as e:
        logger.error(f"Failed to save activation: {e}")
        return False


# ============================================================
# 卖家工具：命令行生成激活码
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        mc = sys.argv[1]
    else:
        mc = input("请输入买家的机器码: ").strip()
    code = generate_activation_code(mc)
    print(f"机器码:   {mc}")
    print(f"激活码:   {code}")
