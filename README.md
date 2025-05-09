# OpenRunTraining

[OpenRunTraining](https://openruntraining.com/)是一个开源项目，目标是建设一个AI训练助手，提高你的越野跑运动表现。


## 技术栈

- 后端：Python Flask
- 前端：
  - Chart.js - 数据可视化
  - Leaflet.js - 地图展示
  - Bootstrap 5 - UI框架
- 数据：
  - Strava API v3
  - Visual Crossing Weather API
- 部署：
  - Nginx - 反向代理服务器
  - Gunicorn - WSGI服务器
  - Let's Encrypt - SSL证书

## 开发日志

### 2025-04-29

1. 修复API接口问题
   - 修复了`/get_default_prompts`接口返回404错误的问题
   - 优化了AI服务的导入和初始化方式
   - 添加了全局CORS支持，解决了跨域请求问题
   - 实现了OPTIONS请求处理，支持CORS预检请求
   - 添加了详细的日志记录，便于问题诊断
   - 修复了GPX上传后无法获取默认提示词的问题

2. 日志系统优化
   - 创建了专门的提示词相关日志(`prompt_debug.log`)
   - 添加了请求和响应详细信息的记录
   - 完善了错误追踪和堆栈信息记录
   - 实现了更全面的调试信息输出

3. 测试工具改进
   - 创建了`test_api.py`脚本用于测试API接口
   - 实现了对API响应的详细检查
   - 添加了响应头和数据内容的验证

### 2025-04-23

1. 欢迎页面优化
   - 实现了独立的欢迎页面，不再直接跳转到Strava授权
   - 添加了项目介绍和功能说明
   - 设计了美观的流程引导界面
   - 优化了Strava登录按钮的视觉效果
   - 完善了授权流程逻辑

2. 路由架构改进
   - 重构了应用路由逻辑，分离欢迎页和用户仪表盘
   - 创建了`/dashboard`路由展示用户数据
   - 优化了未登录用户的重定向逻辑
   - 改进了授权回调处理流程

3. 界面设计升级
   - 添加了流程指引的箭头动画
   - 优化了功能列表的展示方式
   - 增强了按钮交互效果
   - 改进了整体页面布局和响应式设计

### 2025-04-20

1. 服务器部署
   - 使用Gunicorn作为WSGI服务器
   - 配置Nginx作为反向代理
   - 实现多域名支持（openruntraining.com和trailruntraining.com）
   - 申请并配置Let's Encrypt SSL证书
   - 设置HTTP到HTTPS自动重定向

2. 项目结构优化
   - 创建deploy_config目录集中管理部署配置
   - 添加自动化脚本：
     - commands.sh - 常用运维命令（重启服务、查看日志等）
     - backup.sh - 自动备份应用、配置和证书
   - 整理项目文件，提高可维护性
   - 创建logs目录，统一管理日志文件

3. 网站图标
   - 添加网站favicon支持
   - 配置适用于多种设备的图标

4. 文档完善
   - 添加部署文档（deploy_notes.md）
   - 更新README文件，添加部署相关信息

### 2024-04-18

1. 数据可视化优化
   - 移除了不准确的坡度调整配速(GAP)计算和显示
   - 添加了海拔曲线显示
   - 优化了图表样式，使用灰色填充显示海拔数据
   - 在海拔开关旁显示总爬升数据

2. 地图交互增强
   - 实现了图表和地图的联动交互
   - 添加了鼠标悬停时的位置标记功能
   - 优化了标记点的视觉效果
     - 使用了更大的标记点尺寸（20x20像素）
     - 添加了白色边框和阴影效果
     - 实现了呼吸动画效果

3. 界面优化
   - 移除了分段成绩表格中的坡度调整配速列
   - 优化了数据指标的显示方式
   - 改进了整体布局和样式

4. 数据处理优化
   - 优化了移动平均窗口大小（设置为80）
   - 改进了数据点的匹配算法
   - 使用了更精确的距离计算方法

5. 年度活动地图优化
   - 添加了年度活动轨迹汇总地图
   - 实现了按年份切换功能
   - 显示年度活动统计信息（次数、距离、时长）
   - 优化地图显示效果：
     - 使用CartoDB Positron作为底图，提供低饱和度的简洁风格
     - 突出显示运动轨迹（使用Strava标准橙色）
     - 优化轨迹样式（圆角处理、合适的宽度和透明度）
     - 简化地图控件，保留必要功能
   - 智能定位功能：
     - 自动聚焦到活动最频繁的区域
     - 添加"查看所有活动"按钮
     - 使用网格聚类算法计算最活跃区域

### 2024-04-22

1. 历史天气数据功能优化
   - 优化了天气数据容器的布局和样式
   - 调整了天气图表的显示效果
     - 移除了多余的图表标题和图例
     - 优化了图表高度和空间利用
     - 改进了数据点显示方式
   - 添加了数据加载状态提示
     - 显示GPX文件解析状态
     - 显示天气数据获取状态
   - 添加了数据来源标注
   - 实现了与地图容器的高度统一

2. 用户体验改进
   - 优化了加载状态的显示逻辑
   - 改进了错误处理和提示信息
   - 增强了页面布局的响应式表现

3. 代码优化
   - 重构了天气数据处理逻辑
   - 优化了API调用流程
   - 改进了错误处理机制

## 项目结构

```
OpenRunTraining/
├── app.py              # 主应用程序
├── gunicorn_config.py  # Gunicorn配置
├── requirements.txt    # 依赖包
├── .env                # 环境变量
├── logs/               # 日志文件
├── static/             # 静态资源
├── templates/          # HTML模板
└── deploy_config/      # 部署配置和脚本
    ├── commands.sh     # 运维命令脚本
    ├── backup.sh       # 备份脚本
    └── deploy_notes.md # 部署文档
```

## 环境要求

- Python 3.7+
- Flask
- requests
- python-dotenv
- gunicorn (生产环境)
- nginx (生产环境)

## 配置说明

1. 创建`.env`文件并设置以下环境变量：
```
STRAVA_CLIENT_ID=你的客户端ID
STRAVA_CLIENT_SECRET=你的客户端密钥
STRAVA_REDIRECT_URI=你的回调地址
SECRET_KEY=你的密钥
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 运行应用：
```bash
python app.py
```

4. 生产环境部署：
```bash
# 使用gunicorn启动应用
gunicorn -c gunicorn_config.py app:app

# 或使用systemd服务
sudo systemctl start openrun
```

## 贡献指南

欢迎提交Issue和Pull Request来帮助改进这个项目。

## 许可证

MIT License
