# OpenRunTraining 部署笔记

## 服务器信息

- **IP地址**: 43.139.72.39
- **用户**: ubuntu
- **应用路径**: /home/ubuntu/OpenRunTraining
- **操作系统**: Ubuntu 22.04 LTS

## 域名

- openruntraining.com
- www.openruntraining.com
- trailruntraining.com
- www.trailruntraining.com

## 端口

- Nginx: 80(HTTP), 443(HTTPS)
- Gunicorn: 8000(内部)

## SSL证书

- 类型: Let's Encrypt
- 路径: /etc/letsencrypt/live/openruntraining.com/, /etc/letsencrypt/live/trailruntraining.com/
- 有效期: 90天，自动续期
- 续期命令: `sudo certbot renew`

## 服务配置

- Nginx配置: /etc/nginx/sites-available/openrun_domains.conf
- Gunicorn配置: ~/OpenRunTraining/gunicorn_config.py
- systemd服务: /etc/systemd/system/openrun.service

## 日志位置

- Nginx日志:
  - 访问日志: /var/log/nginx/openrun_access.log, /var/log/nginx/trailrun_ssl_access.log
  - 错误日志: /var/log/nginx/openrun_error.log, /var/log/nginx/trailrun_ssl_error.log
- Gunicorn日志:
  - 访问日志: ~/OpenRunTraining/logs/access.log
  - 错误日志: ~/OpenRunTraining/logs/error.log
- 系统服务日志: `sudo journalctl -u openrun`

## 数据库

- 类型: 目前使用内存存储，无持久化数据库

## 备份

- 脚本: ~/OpenRunTraining/deploy_config/backup.sh
- 备份内容: 应用代码、配置文件、SSL证书
- 建议备份频率: 每周一次或代码更新后

## 部署流程

1. 代码更新: `git pull`
2. 安装依赖: `pip install -r requirements.txt`
3. 重启服务: `sudo systemctl restart openrun`
4. 验证运行: `curl http://localhost:8000`

## 常用管理命令

管理脚本: ~/OpenRunTraining/deploy_config/commands.sh

```bash
# 重启服务
./deploy_config/commands.sh restart

# 查看日志
./deploy_config/commands.sh logs

# 查看服务状态
./deploy_config/commands.sh status

# 刷新SSL证书
./deploy_config/commands.sh ssl
```

## 注意事项

1. 应用运行用户为ubuntu，确保文件权限正确
2. 修改Nginx配置后需要测试: `sudo nginx -t`
3. 增加新域名时需要申请新的SSL证书: `sudo certbot --nginx -d 新域名`
4. 应用使用Strava API，确保.env文件中的密钥和回调URL正确配置 