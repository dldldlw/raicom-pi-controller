# 硬件接线表

> 所有引脚均为 **BCM 编号**（即 `GPIO.setmode(GPIO.BCM)` 下使用的编号，
> 不是物理针脚序号）。
>
> 全部引脚集中在 `config.py` 里定义，改接线只改那一个文件。

## 1. 步进电机（三线接法：使能 + 方向 + 脉冲）

驱动器按 TB6600 / DM542 这类"ENA / DIR / PUL"接口的电平接法。

| 功能 | 电机名 | ENA | DIR | PUL |
|---|---|---|---|---|
| 上下（垂直） | `MOTOR_UP_DOWN` | GPIO 12 | GPIO 18 | GPIO 19 |
| 左右（水平） | `MOTOR_LEFT_RIGHT` | GPIO 23 | GPIO 27 | GPIO 22 |
| 前后（进给） | `MOTOR_FWD_BACK` | GPIO 6 | GPIO 25 | GPIO 5 |

* ENA **低电平使能**、高电平失能；上电时初始化为失能，避免上电乱转。
* 驱动器共阳/共阴接法不同，若电机不转先确认 ENA 极性。

## 2. TCRT5000 红外对管 + 舵机夹爪

| 功能 | BCM GPIO | 说明 |
|---|---|---|
| TCRT5000 OUT | GPIO 17 | 数字量输出，`GPIO.IN` |
| 舵机信号 | GPIO 4 | 50 Hz PWM，`GPIO.OUT` |

* 舵机角度换算：`duty = angle / 18 + 2`（对应 50 Hz 下 0.5–2.5 ms 脉宽）。
* 夹紧角度 20°，松开角度 90°。

## 3. 与 K230 的串口

| 树莓派 | K230 | 说明 |
|---|---|---|
| USB 口（经 USB 转串口） | UART2 | 树莓派侧设备名 `/dev/ttyUSB0` |
| — | TXD = GPIO 11 | K230 的 FPIOA 配置 |
| — | RXD = GPIO 12 | K230 的 FPIOA 配置 |

* 波特率 **115200**，8 数据位，无校验，1 停止位。
* TX / RX 需要**交叉连接**。

## ⚠️ 踩过的坑：GPIO 18 冲突

最初的接线把舵机信号线接在了 GPIO 18 上，而 GPIO 18 同时是**上下电机的 DIR 脚**。
两个外设抢同一个引脚，表现是电机方向乱跳 / 舵机抽搐。

解决办法是把舵机改到 **GPIO 4**。现在这个约束写在 `config.py` 的注释里，
并且 `jg_cgq.py`、`stepper_motor.py` 的自测块都从 `config.py` 读引脚，
不会再出现"主程序改了、自测块没改"的情况。

## 引脚占用总览（自查用）

```
GPIO 4  舵机信号
GPIO 5  前后电机 PUL
GPIO 6  前后电机 ENA
GPIO 12 上下电机 ENA
GPIO 17 TCRT5000 OUT
GPIO 18 上下电机 DIR      <-- 不要再接舵机
GPIO 19 上下电机 PUL
GPIO 22 左右电机 PUL
GPIO 23 左右电机 ENA
GPIO 25 前后电机 DIR
GPIO 27 左右电机 DIR
```

改接线后可以拿这张表对一遍，确认没有重复。
