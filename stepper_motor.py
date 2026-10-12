# -*- coding: utf-8 -*-
"""
stepper_motor.py - 步进电机控制库

封装"使能(ENA) + 方向(DIR) + 脉冲(PUL)"三线接法的步进电机驱动器，
支持匀速运动与带软启动/软停止的加减速运动。

用法::

    import RPi.GPIO as GPIO
    import config
    from stepper_motor import StepperMotor

    motor = StepperMotor(**config.MOTOR_UP_DOWN)
    motor.rotate(steps=50, direction=GPIO.HIGH, delay=0.0001)
    motor.cleanup()

相对原版的改动
--------------
* 自测块改为从 config.py 读引脚。原来自测块里硬编码的 motor1 dir_pin=18
  会和 jg_cgq.py 自测块里的 SERVO_PIN=18 撞脚。
* 类本身的运动逻辑一行未改（赛场上验证过，不动）。
"""

import math
import time

import RPi.GPIO as GPIO

import config


class StepperMotor:
    """步进电机控制类

    参数:
        ena_pin: 使能控制引脚（低电平使能）
        dir_pin: 方向控制引脚
        pul_pin: 脉冲控制引脚
        name:    电机名称（仅用于打印）
    """

    def __init__(self, ena_pin, dir_pin, pul_pin, name="Stepper Motor"):
        self.ENA = ena_pin
        self.DIR = dir_pin
        self.PUL = pul_pin
        self.name = name

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        GPIO.setup(self.ENA, GPIO.OUT)
        GPIO.setup(self.DIR, GPIO.OUT)
        GPIO.setup(self.PUL, GPIO.OUT)

        # 初始禁用电机
        GPIO.output(self.ENA, GPIO.HIGH)
        # 初始方向
        GPIO.output(self.DIR, GPIO.LOW)

    def enable(self):
        """使能电机"""
        GPIO.output(self.ENA, GPIO.LOW)

    def disable(self):
        """禁用电机"""
        GPIO.output(self.ENA, GPIO.HIGH)

    def set_direction(self, direction):
        """设置电机方向

        参数:
            direction: True/False 或 GPIO.HIGH/GPIO.LOW
        """
        GPIO.output(self.DIR, direction)

    def rotate(self, steps, direction, delay=0.0005):
        """匀速旋转指定步数

        参数:
            steps:     旋转步数
            direction: 旋转方向（True/False 或 GPIO.HIGH/GPIO.LOW）
            delay:     半周期延时（秒）。一个完整脉冲耗时 2 × delay。

        注意:
            这里是软件延时 bit-bang，受 Python / 系统调度抖动影响，
            delay 很小时（< 0.0001s）容易丢步。
        """
        self.enable()
        self.set_direction(direction)

        for _ in range(steps):
            GPIO.output(self.PUL, GPIO.HIGH)
            time.sleep(delay)
            GPIO.output(self.PUL, GPIO.LOW)
            time.sleep(delay)

    def rotate_soft(self, steps, direction,
                    max_delay=0.005, min_delay=0.0001,
                    accel_steps=300, decel_steps=300):
        """带软启动 / 软停止的旋转

        参数:
            steps:       总步数
            direction:   旋转方向
            max_delay:   启动时的最大延时（最低速度）
            min_delay:   匀速段的最小延时（最高速度）
            accel_steps: 加速阶段步数
            decel_steps: 减速阶段步数

        注意:
            加速/减速步数会被夹到 steps // 2 以内。当前 main.py 未使用本方法
            （仍然走 rotate 的硬启停），保留作为后续提速的备选。
        """
        self.enable()
        self.set_direction(direction)

        accel_steps = min(accel_steps, steps // 2)
        decel_steps = min(decel_steps, steps // 2)
        const_steps = steps - accel_steps - decel_steps

        # 加速阶段（软启动）：指数逼近 min_delay
        for step in range(accel_steps):
            ratio = step / accel_steps
            current_delay = max_delay * math.exp(-3.5 * ratio)
            current_delay = max(min_delay, current_delay)

            GPIO.output(self.PUL, GPIO.HIGH)
            time.sleep(current_delay)
            GPIO.output(self.PUL, GPIO.LOW)
            time.sleep(current_delay)

        # 匀速阶段
        for _ in range(const_steps):
            GPIO.output(self.PUL, GPIO.HIGH)
            time.sleep(min_delay)
            GPIO.output(self.PUL, GPIO.LOW)
            time.sleep(min_delay)

        # 减速阶段（软停止）：指数逼近 max_delay
        for step in range(decel_steps):
            ratio = step / decel_steps
            current_delay = min_delay * math.exp(3.5 * ratio)
            current_delay = min(max_delay, current_delay)

            GPIO.output(self.PUL, GPIO.HIGH)
            time.sleep(current_delay)
            GPIO.output(self.PUL, GPIO.LOW)
            time.sleep(current_delay)

    def cleanup(self):
        """禁用电机。

        注意: 这里不调用 GPIO.cleanup()，因为其它电机还在用同一批 GPIO，
        全局清理在 main.py 退出时统一执行。
        """
        self.disable()


# ---------------------------------------------------------------------------
# 自测块: 单独运行本文件可逐个点动三个电机
#     sudo python3 stepper_motor.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("步进电机自测（引脚取自 config.py）")
    motor1 = StepperMotor(**config.MOTOR_UP_DOWN)
    motor2 = StepperMotor(**config.MOTOR_LEFT_RIGHT)

    try:
        print("测试 motor1（上下电机）匀速运动...")
        motor1.rotate(steps=100, direction=GPIO.HIGH, delay=0.001)
        time.sleep(0.5)
        motor1.rotate(steps=100, direction=GPIO.LOW, delay=0.001)

        print("测试 motor2（左右电机）匀速运动...")
        motor2.rotate(steps=100, direction=GPIO.HIGH, delay=0.001)

        print("测试 motor1 加减速运动...")
        motor1.rotate_soft(steps=500, direction=GPIO.HIGH,
                           max_delay=0.005, min_delay=0.0005,
                           accel_steps=100, decel_steps=100)
        time.sleep(0.5)
        motor1.rotate_soft(steps=500, direction=GPIO.LOW,
                           max_delay=0.005, min_delay=0.0005,
                           accel_steps=100, decel_steps=100)
    finally:
        GPIO.cleanup()
        print("GPIO 清理完成")
