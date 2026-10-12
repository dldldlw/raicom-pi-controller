# -*- coding: utf-8 -*-
"""
jg_cgq.py - TCRT5000 红外对管 + 舵机夹爪

把"检测到一个电平变化 -> 让舵机夹紧再松开"这套动作封装成类。

用法::

    import config
    from jg_cgq import TCRT5000_Servo_Trigger

    trigger = TCRT5000_Servo_Trigger(
        sensor_pin=config.SENSOR_PIN,
        servo_pin=config.SERVO_PIN,
        grab_angle=config.GRAB_ANGLE,
        release_angle=config.RELEASE_ANGLE,
    )
    if trigger.check_trigger():
        trigger.grab()
        trigger.release()

相对原版的改动
--------------
* 删掉了从未被使用的 trigger_duration_ms 参数（死参数）
* 自测块的 SERVO_PIN 改为从 config.py 读（原来是 18，会和上下电机的 DIR 撞脚）
* 新增可选的 debounce_count（默认 1 = 与原行为完全一致，不改变赛场行为）
* 新增可选的 hold_torque（默认 False = 与原行为一致）
"""

import time

import RPi.GPIO as GPIO

import config


class TCRT5000_Servo_Trigger:
    """红外对管触发 + 舵机夹爪

    参数:
        sensor_pin:     TCRT5000 的 OUT 引脚（GPIO.IN）
        servo_pin:      舵机信号引脚（GPIO.OUT，50Hz PWM）
        grab_angle:     夹紧角度
        release_angle:  松开角度
        grab_time:      夹紧到位后额外等待时长（秒）
        servo_settle_s: 舵机转到目标角度后的稳定时间（秒）
        debounce_count: 确认一次电平变化需要连续采样到的次数。
                        1 = 与原实现完全一致（第一次变化立刻触发）。
                        调大可以抑制线路噪声导致的误触发。
        hold_torque:    True  = 到位后持续输出 PWM，舵机保持力矩（耗电、发热）
                        False = 与原实现一致，到位后把占空比写 0，避免舵机抖舵
    """

    def __init__(self, sensor_pin, servo_pin,
                 grab_angle=70, release_angle=110, grab_time=0.5,
                 servo_settle_s=0.3, debounce_count=1, hold_torque=False):
        self.sensor_pin = sensor_pin
        self.servo_pin = servo_pin
        self.grab_angle = grab_angle
        self.release_angle = release_angle
        self.grab_time = grab_time
        self.servo_settle_s = servo_settle_s

        self.debounce_count = max(1, int(debounce_count))
        self.hold_torque = hold_torque

        self.last_level = None   # 上一次确认过的传感器电平
        self._same_count = 0     # 去抖计数

        self._init_gpio()
        self._init_servo()

    # ---------------------------------------------------------------- 初始化
    def _init_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.sensor_pin, GPIO.IN)
        GPIO.setup(self.servo_pin, GPIO.OUT)

    def _init_servo(self):
        self.servo_pwm = GPIO.PWM(self.servo_pin, 50)  # 50Hz
        self.servo_pwm.start(0)
        self.release()
        time.sleep(0.5)

    # ------------------------------------------------------------------ 舵机
    def set_servo_angle(self, angle):
        """让舵机转到指定角度，等待稳定后（可选）释放 PWM。"""
        duty = angle / 18 + 2
        self.servo_pwm.ChangeDutyCycle(duty)
        time.sleep(self.servo_settle_s)
        if not self.hold_torque:
            # 占空比归零，避免舵机持续吱吱响 / 抖舵。
            # 代价是失去保持力矩，夹紧状态下可能被工件顶开。
            self.servo_pwm.ChangeDutyCycle(0)

    def grab(self):
        """夹紧"""
        self.set_servo_angle(self.grab_angle)
        time.sleep(self.grab_time)

    def release(self):
        """松开"""
        self.set_servo_angle(self.release_angle)

    # ---------------------------------------------------------------- 传感器
    def read_sensor_level(self):
        """读当前电平（0 = 未检测到反射，1 = 检测到反射）"""
        return GPIO.input(self.sensor_pin)

    def check_trigger(self):
        """检测电平变化（上升沿或下降沿都算）

        返回 True 表示确认了一次新的电平变化。
        第一次调用只是记录初始电平，返回 False。

        debounce_count > 1 时，需要连续采样到同样的新电平才算确认，
        用于抑制线路噪声。默认 1 时与原实现行为完全一致。
        """
        current_level = self.read_sensor_level()

        # 第一次调用只记录基线
        if self.last_level is None:
            self.last_level = current_level
            return False

        if current_level == self.last_level:
            self._same_count = 0
            return False

        # 电平变了，需要连续确认 debounce_count 次
        self._same_count += 1
        if self._same_count < self.debounce_count:
            return False

        self.last_level = current_level
        self._same_count = 0
        return True

    # --------------------------------------------------------------- 独立运行
    def run(self, repeat=3):
        """独立监控循环：每次检测到电平变化就执行 repeat 次夹取动作。

        这是脱离 main.py 的调试入口，不参与正式比赛流程。
        """
        try:
            print("开始监控电平变化...（按 Ctrl+C 退出）")
            while True:
                if self.check_trigger():
                    print(f"检测到电平变化（当前电平: {self.last_level}），"
                          f"延时 0.2 秒后执行 {repeat} 次夹取动作！")
                    time.sleep(0.2)

                    for i in range(repeat):
                        print(f"执行第 {i + 1}/{repeat} 次夹取动作")
                        self.grab()
                        self.release()
                        if i < repeat - 1:
                            time.sleep(0.5)

                    print(f"{repeat} 次夹取动作完成")

                time.sleep(0.001)
        except KeyboardInterrupt:
            print("\n程序退出")
        finally:
            self.cleanup()

    def cleanup(self):
        """回位 -> 停 PWM -> 释放本类占用的两个 GPIO"""
        self.release()
        time.sleep(0.5)
        self.servo_pwm.stop()
        GPIO.cleanup([self.sensor_pin, self.servo_pin])
        print("GPIO 资源已释放")


if __name__ == "__main__":
    # 独立自测：引脚统一取自 config.py
    trigger_system = TCRT5000_Servo_Trigger(
        sensor_pin=config.SENSOR_PIN,
        servo_pin=config.SERVO_PIN,
        grab_angle=config.GRAB_ANGLE,
        release_angle=config.RELEASE_ANGLE,
        grab_time=config.GRAB_TIME,
        servo_settle_s=config.SERVO_SETTLE_S,
    )
    trigger_system.run()
