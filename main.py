# -*- coding: utf-8 -*-
"""
main.py - 树莓派下位机主程序

职责
----
1. 打开与 K230 的串口（USB 转串口，/dev/ttyUSB0 @115200）
2. 上电 3 秒后向 K230 发送 0xAA，表示"我准备好了"
3. 逐字节接收 K230 指令，驱动三轴步进电机 / 红外触发夹爪

指令表见 docs/protocol.md，引脚定义见 config.py。

用法
----
    sudo python3 main.py

相对原版的改动
--------------
* 引脚、角度、串口参数全部移到 config.py
* 补上 0xCC 的处理分支（原版没有这个分支，K230 的收工信号被静默丢弃）
* 修正两处注释与代码不符："延时0.2秒" 实为 100 步 ≈ 0.02 秒；
  "三次夹取" 实为 range(5) 五次
* 串口打开失败时给出可操作的提示，而不是直接抛 traceback
* 加 if __name__ == "__main__" 守卫，import 本模块不再会初始化硬件
* 退出时补上全局 GPIO.cleanup()
"""

import sys
import time

import RPi.GPIO as GPIO
import serial

import config
from jg_cgq import TCRT5000_Servo_Trigger
from stepper_motor import StepperMotor


def open_serial():
    """打开串口。失败时返回 None 并打印排查步骤。"""
    try:
        ser = serial.Serial(
            port=config.SERIAL_PORT,
            baudrate=config.SERIAL_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=config.SERIAL_TIMEOUT,
        )
        print(f"串口已打开: {config.SERIAL_PORT} @ {config.SERIAL_BAUDRATE}")
        return ser
    except serial.SerialException as exc:
        print(f"[错误] 无法打开串口 {config.SERIAL_PORT}: {exc}")
        print("       排查步骤:")
        print("         1) K230 的 USB 转串口是否插好")
        print("         2) ls /dev/ttyUSB* 确认真实设备名，必要时改 config.SERIAL_PORT")
        print("         3) 当前用户是否在 dialout 组: sudo usermod -aG dialout $USER")
        return None


def handle_motor3_with_sensor(motor3, trigger_system):
    """前后电机边前进边等红外触发，触发后执行夹取动作，然后返回。

    ⚠️ 这个函数是阻塞的。抓取全过程（约 GRAB_REPEAT × 0.9 秒）期间主循环
    无法响应其它串口指令。比赛流程如果需要并发，应改成非阻塞状态机。
    """
    motor3.enable()
    motor3.set_direction(GPIO.HIGH)   # 正转 = 前进方向

    trigger_system.last_level = None  # 重置传感器状态，避免带着旧电平进来

    try:
        print("电机3运行中，监控红外对管电平变化...")
        while True:
            # 走一步
            GPIO.output(motor3.PUL, GPIO.HIGH)
            time.sleep(config.PULSE_DELAY)
            GPIO.output(motor3.PUL, GPIO.LOW)
            time.sleep(config.PULSE_DELAY)

            # 检测电平变化
            if not trigger_system.check_trigger():
                continue

            print("检测到电平变化! 电机3继续前进，之后执行夹取动作")

            if config.POST_TRIGGER_DELAY_S is not None:
                # 真的延时（原注释所描述的行为）
                time.sleep(config.POST_TRIGGER_DELAY_S)
            else:
                # 保持原行为：用继续走步代替延时
                # 注意 100 步 × (PULSE_DELAY × 2) ≈ 0.02 秒，不是注释里写的 0.2 秒
                for _ in range(config.POST_TRIGGER_STEPS):
                    GPIO.output(motor3.PUL, GPIO.HIGH)
                    time.sleep(config.PULSE_DELAY)
                    GPIO.output(motor3.PUL, GPIO.LOW)
                    time.sleep(config.PULSE_DELAY)

            for i in range(config.GRAB_REPEAT):
                print(f"执行第 {i + 1}/{config.GRAB_REPEAT} 次夹取动作")
                trigger_system.grab()
                trigger_system.release()
                if i < config.GRAB_PAUSE_AFTER:
                    time.sleep(config.GRAB_PAUSE_S)

            print(f"{config.GRAB_REPEAT} 次夹取动作完成")
            time.sleep(0.01)  # 防止连续触发
            break

    except KeyboardInterrupt:
        print("电机3控制中断")
    finally:
        motor3.disable()


def dispatch(cmd, motors, trigger_system):
    """处理一条指令。返回 True 表示应当退出主循环。"""
    motor1, motor2, motor3 = motors

    if cmd == config.CMD_MOTOR1_REV:
        print("收到指令 0x0D: 上下电机反转")
        motor1.rotate(steps=config.STEPS_PER_COMMAND, direction=GPIO.LOW,
                      delay=config.PULSE_DELAY)

    elif cmd == config.CMD_MOTOR1_FWD:
        print("收到指令 0x0E: 上下电机正转")
        motor1.rotate(steps=config.STEPS_PER_COMMAND, direction=GPIO.HIGH,
                      delay=config.PULSE_DELAY)

    elif cmd == config.CMD_MOTOR2_FWD:
        print("收到指令 0x0C: 左右电机正转")
        motor2.rotate(steps=config.STEPS_PER_COMMAND, direction=GPIO.HIGH,
                      delay=config.PULSE_DELAY)

    elif cmd == config.CMD_MOTOR2_REV:
        print("收到指令 0x0B: 左右电机反转")
        motor2.rotate(steps=config.STEPS_PER_COMMAND, direction=GPIO.LOW,
                      delay=config.PULSE_DELAY)

    elif cmd == config.CMD_START_GRAB:
        # 预留入口：比赛中从未收到过这个字节。
        # 当时的红外夹取是在树莓派 REPL 里直接调 handle_motor3_with_sensor()
        # 触发的，完全不经过串口。想走串口路径就发一个 0xFF，效果完全一致；
        # tools/trigger_grab.py 走的则是直接调用那条路。
        print("收到指令 0xFF: 启动红外触发夹取流程")
        handle_motor3_with_sensor(motor3, trigger_system)

    elif cmd == config.CMD_TARGET_CENTERED:
        # 新增分支：原版没有处理 0xCC，K230 的收工信号会被静默丢弃
        print("收到指令 0xCC: K230 报告目标已居中")
        motor1.disable()
        motor2.disable()
        motor3.disable()
        if config.EXIT_ON_TARGET_CENTERED:
            print("收工，退出主循环")
            return True
        print("EXIT_ON_TARGET_CENTERED=False，继续等待指令")

    else:
        print(f"收到未知指令 0x{cmd:02X}，已忽略")

    return False


def main():
    motors = [
        StepperMotor(**config.MOTOR_UP_DOWN),
        StepperMotor(**config.MOTOR_LEFT_RIGHT),
        StepperMotor(**config.MOTOR_FWD_BACK),
    ]

    trigger_system = TCRT5000_Servo_Trigger(
        sensor_pin=config.SENSOR_PIN,
        servo_pin=config.SERVO_PIN,
        grab_angle=config.GRAB_ANGLE,
        release_angle=config.RELEASE_ANGLE,
        grab_time=config.GRAB_TIME,
        servo_settle_s=config.SERVO_SETTLE_S,
    )

    ser = open_serial()
    if ser is None:
        trigger_system.cleanup()
        for motor in motors:
            motor.cleanup()
        GPIO.cleanup()
        return 1

    exit_code = 0
    try:
        print("串口控制程序已启动，等待指令...")
        time.sleep(3)  # 给 K230 留出上电启动时间
        ser.write(bytes([config.SERIAL_READY_BYTE]))
        print(f"已发送就绪信号 0x{config.SERIAL_READY_BYTE:02X}")

        while True:
            data = ser.read()
            if not data:
                continue
            if dispatch(ord(data), motors, trigger_system):
                break

    except KeyboardInterrupt:
        print("\n程序被用户中断")
    finally:
        ser.close()
        for motor in motors:
            motor.cleanup()
        trigger_system.cleanup()
        GPIO.cleanup()
        print("串口关闭，GPIO 清理完成")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
