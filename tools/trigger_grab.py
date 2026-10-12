# -*- coding: utf-8 -*-
"""
tools/trigger_grab.py - 单独触发一次红外夹取流程

为什么会有这个脚本
------------------
比赛时这一步是**直接在树莓派上的 REPL 里手动调用** `handle_motor3_with_sensor()`
完成的 —— 没有走串口，也没有经过 K230。所以原工程里虽然写了 `0xFF` 的串口
分支，却从来没有任何东西会发送这个字节，它是一段未被使用的死入口。

这个脚本把当年"手敲函数调用"这个操作固化成一个可版本管理的入口，
让这条链路可复现、可被后来的人看懂。

流程
----
1. 初始化前后电机 + TCRT5000 红外对管 + 舵机
2. 调用 `handle_motor3_with_sensor()`:
      电机持续前进 → 红外检测到电平变化 → 再前进 POST_TRIGGER_STEPS 步
      → 执行 GRAB_REPEAT 次"夹紧-松开"
3. 清理 GPIO

用法
----
    sudo python3 tools/trigger_grab.py

不需要串口，也不依赖 K230 在线。按 Ctrl+C 可中断。
想走串口路径的话，往 /dev/ttyUSB0 写一个字节 0xFF 效果完全相同。
"""

import os
import sys

# 允许从 tools/ 子目录直接运行：把仓库根目录加进模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import RPi.GPIO as GPIO  # noqa: E402

import config  # noqa: E402
from jg_cgq import TCRT5000_Servo_Trigger  # noqa: E402
from main import handle_motor3_with_sensor  # noqa: E402
from stepper_motor import StepperMotor  # noqa: E402


def main():
    print("=" * 60)
    print("红外触发夹取 - 单次触发")
    print(f"  前后电机: ENA={config.MOTOR_FWD_BACK['ena_pin']} "
          f"DIR={config.MOTOR_FWD_BACK['dir_pin']} "
          f"PUL={config.MOTOR_FWD_BACK['pul_pin']}")
    print(f"  红外对管: GPIO{config.SENSOR_PIN}   舵机: GPIO{config.SERVO_PIN}")
    print(f"  触发后前进 {config.POST_TRIGGER_STEPS} 步，夹取 {config.GRAB_REPEAT} 次")
    print("=" * 60)

    motor3 = StepperMotor(**config.MOTOR_FWD_BACK)
    trigger_system = TCRT5000_Servo_Trigger(
        sensor_pin=config.SENSOR_PIN,
        servo_pin=config.SERVO_PIN,
        grab_angle=config.GRAB_ANGLE,
        release_angle=config.RELEASE_ANGLE,
        grab_time=config.GRAB_TIME,
        servo_settle_s=config.SERVO_SETTLE_S,
    )

    try:
        handle_motor3_with_sensor(motor3, trigger_system)
        print("夹取流程结束")
    except KeyboardInterrupt:
        print("\n被用户中断")
    finally:
        motor3.cleanup()
        trigger_system.cleanup()
        GPIO.cleanup()
        print("GPIO 清理完成")

    return 0


if __name__ == "__main__":
    sys.exit(main())
