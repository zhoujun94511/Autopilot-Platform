# coturn 部署

1. 复制 `.env.example` 为 `.env`，生成独立于 JWT 的 32 字节以上随机密钥。
2. `TURN_EXTERNAL_IP` 填 coturn 公网 IP；NAT 后部署时使用 `公网IP/内网IP`。
3. Platform 配置相同的 `MC_TURN_SECRET`，并设置：

```env
MC_TURN_ENABLED=1
MC_TURN_REALM=autopilot.example.com
MC_TURN_URLS=stun:turn.example.com:3478,turn:turn.example.com:3478?transport=udp,turn:turn.example.com:3478?transport=tcp,turns:turn.example.com:5349?transport=tcp
MC_TURN_SECRET=<与 TURN_STATIC_AUTH_SECRET 相同>
MC_TURN_CREDENTIAL_TTL_SEC=3600
```

4. 放行 `3478/tcp,udp`、`5349/tcp` 和 `49160-49200/udp`。
5. 启动：`docker compose -f docker-compose.coturn.yml up -d`。

生产环境应给 `turns:` 配置有效证书；将证书放进 `certs/` 并取消
`turnserver.conf` 的 `cert`/`pkey` 注释。扩大 relay 端口段时须同时修改
compose 映射、coturn 参数与防火墙。
