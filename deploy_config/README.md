# OpenRunTraining 部署配置

本目录包含用于部署OpenRunTraining应用的所有配置文件。

## 文件说明

- **gunicorn_config.py**: Gunicorn WSGI服务器配置文件
- **openrun.service**: systemd服务配置文件
- **openrun_domains.conf**, **openrun_domains_fixed.conf**: Nginx虚拟主机配置文件
- **openrun.conf**, **openrun.nginx**: 旧的Nginx配置文件（备份用）
- **.env**: 环境变量配置文件
- **requirements.txt**: Python依赖列表
- **access.log**, **error.log**: Gunicorn日志文件

## 部署步骤

1. 安装Python依赖：
   ```
   pip install -r requirements.txt
   ```

2. 配置Nginx：
   ```
   sudo cp openrun_domains_fixed.conf /etc/nginx/sites-available/openrun_domains.conf
   sudo ln -sf /etc/nginx/sites-available/openrun_domains.conf /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

3. 配置systemd服务：
   ```
   sudo cp openrun.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable openrun
   sudo systemctl start openrun
   ```

## 域名

应用支持以下域名：
- openruntraining.com
- www.openruntraining.com
- trailruntraining.com
- www.trailruntraining.com
- 43.139.72.39 (IP地址)

## SSL证书

应用使用Let's Encrypt提供的SSL证书。证书会自动续期。

## 日志位置

- Nginx日志: `/var/log/nginx/`
- Gunicorn日志: `access.log` 和 `error.log`
- 系统服务日志: `sudo journalctl -u openrun`

## 重启服务

```
sudo systemctl restart openrun
sudo systemctl restart nginx
```

## 查看服务状态

```
sudo systemctl status openrun
sudo systemctl status nginx
``` 