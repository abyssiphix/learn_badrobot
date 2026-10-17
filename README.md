# BadRobot 复现学习记录

基于 Code as Policies 官方代码进行仿真实验与代码学习。

## 上游来源
- https://github.com/google-research/google-research/tree/master/code_as_policies
- 官方源码 commit：3ef52111c1fabc301880818f5a547570e926a76b
- https://github.com/Rookie143/BadRobot

## 当前实现
- UR5e + Robotiq，PyBullet 仿真。
- 模型接口适配为 DeepSeek；具体版本见实验调用记录。
- 使用 TinyRenderer。
- knife/person 使用新建几何代理，并非论文原始资产。
- 正常任务五个场景通过；一组直接请求与改写请求均触发代理接触。
- 改写的语义等价性尚未成立，不能据此宣称概念欺骗提高成功率。
- 尚未完成三种攻击方法的系统评估。

## 环境与运行
Python 3.10；安装版本见 requirements-lock.txt。
生成环境、LMP 和运行实验的方法见 README.txt 及各脚本。
assets 需通过 prepare_cap_env.py 从官方来源另行准备；
该脚本需要传入已检出的官方 Interactive_Demo.ipynb 路径。
本仓库不包含完整实验输出、视频或模型资产。

## 复现边界
这是更换模型、接口和场景后的适配实验，不是论文原始数值的严格复现。
当前接触指标不表示真实伤害；无接触也不自动表示模型安全拒绝。
原版 exec_safe 不是安全沙箱，实验代码仅用于仿真。

## 来源记录与版权
manifest.json、lmp_manifest.json 记录提取和修改。
original_cells/、original_lmp_cells/ 保留原始单元格。
第三方代码版权与许可见 UPSTREAM_LICENSE.txt、
LMP_UPSTREAM_LICENSE.txt 及文件中的声明。
