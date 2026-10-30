# Windowsの模擬設備からVMware上のUbuntuへ接続する

対象：Windowsホスト、VMwareのUbuntu 24.04、VMのIP **192.168.237.128**。
ここで入力するのはMQTT Brokerのアドレス。Python受信器のヘルスHTTPポート8081やPostgreSQLの5432へ遥測を送る構成ではない。

```text
Windows: C++/Qt模擬設備 → Ubuntu VM: Mosquitto Broker → Python受信器 → PostgreSQL
Windows: 指令送信器    → Ubuntu VM: 同じBroker       → 対象の模擬設備
```

## まずSSHトンネルで接続する

現在のローカルBroker設定を使って確認する方法。
VM側のMosquittoを127.0.0.1:18884で動かし、Windowsの127.0.0.1:18884からSSH経由でそこへ転送する。
VMのBrokerを外部へ公開したり、MQTT用の証明書を発行したりする必要はない。

Ubuntu VM側：

```bash
# VMのIPとMQTT/SSHの待受ポートを確認する
ip -br address
ss -ltn | rg ':22|:18884'
# SSHサーバーが未導入の場合に導入し、起動する
sudo apt install openssh-server
sudo systemctl enable --now ssh
# 開発用Brokerが18884で動いていない場合だけ、この端末で起動する
mosquitto -p 18884
```

既に18884のBrokerが動いている場合は二重起動しない。別端末で受信器を起動する。

```bash
# TMRPルートへ移動する
cd ~/pythonLearning/TMRP
# 既存の開発DBを受信器へ渡す
export TMRP_RECEIVER_DSN='host=/var/run/postgresql dbname=tmrp_dev user=shou'
# テーブルを初期化し、受信器を起動する（既存サービス稼働中なら重複起動しない）
bash scripts/server/start_server.sh --init-db
```

Windows PowerShell側：

```powershell
# VMのSSHへ到達できるか確認する
Test-NetConnection 192.168.237.128 -Port 22
# Windowsの18884をVM内の18884へ転送する。この端末は開いたままにする
# shouはUbuntu上のユーザー名。異なる場合は置き換える
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
  -L 127.0.0.1:18884:127.0.0.1:18884 shou@192.168.237.128
```

初回のSSHホスト鍵はUbuntu側の鍵指紋と照合する。Windows側の18884が使用中なら左側のみ18885へ変更し、アプリのポートも18885にする。
トンネルはSSHの暗号化を利用する。Windowsへ公開するローカル待受は127.0.0.1に限定している。

アプリの各設備に次を設定する：

| 項目 | 値 |
|---|---|
| 機器ID | `power-meter-001`〜`power-meter-012`、設備ごとに別ID |
| 設備ID | `breaker-001`〜`breaker-012` |
| Broker IP | **127.0.0.1**（SSHトンネルの入口） |
| ポート | **18884** |
| 送信元IP | 空欄 |
| TLS | オフ（MQTTはトンネル内、SSHが暗号化する） |
| 送信頻度 | まず1 Hz |

「接続」→「定期送信を開始」。複数設備は「全設備の定期送信」でも接続・送信できる。
Brokerへ接続できても、台帳未登録の機器はPython受信器が拒否する。

VM側で確認する：

```bash
# Brokerに遥測が到着しているか確認する
mosquitto_sub -h 127.0.0.1 -p 18884 -t 'tmrp/devices/+/telemetry' -q 1 -v
# 別端末で受信器の処理件数を確認する
curl --fail http://127.0.0.1:8081/health/ready
# 開発DBの機器別保存件数を確認する
psql 'host=/var/run/postgresql dbname=tmrp_dev user=shou' \
  -c 'SELECT device_id, count(*) FROM power_telemetry GROUP BY device_id ORDER BY device_id;'
```

## 指令の往復を確認する

開閉指令の往復もVM側から確認できる。アプリを接続したまま、TMRPルートで実行する。

```bash
# 設備001へ開指令を送り、受付・完了結果を表示する。再送用JSONも保存する
.venv/bin/python device-simulator/scripts/send_command.py \
  --operation open_breaker --save-command /tmp/open-command-001.json
# 同じ指令を再送する。二重実行せず保存済み結果が返る
.venv/bin/python device-simulator/scripts/send_command.py \
  --command-file /tmp/open-command-001.json
# 設備002へ閉指令を送る
.venv/bin/python device-simulator/scripts/send_command.py \
  --device-id power-meter-002 --equipment-id breaker-002 --operation close_breaker
```

アプリで対象設備の「受信指令・操作結果」と遮断器状態を確認する。
保存先JSONが既に存在する場合は上書きせず停止するので、別名を指定する。

## VMのIPへ直接接続する場合

アプリのBroker IPを**192.168.237.128**、ポートを**8883**、TLSをオンにする。
この場合はVM側BrokerにTLS listener、認証、ACLを設定し、クライアントへCA証明書を渡す。

- サーバー証明書のSANに`IP:192.168.237.128`を含める。DNS名で接続する場合はそのDNS名のSANを使用する。
- 既存のローカルlistener 18884は残し、Python受信器は同じBrokerのローカルlistenerへ接続できる。
- Mosquittoの`listener 8883`、`certfile`、`keyfile`、`password_file`、`acl_file`を設定する。パスや資格情報は環境ごとに管理する。
- listenerごとに認証方式を分ける場合は`per_listener_settings true`を設定し、対応するlistenerの後へ認証設定を書く。
- Windows側は公開CA証明書だけを指定する。サーバー秘密鍵・CA秘密鍵をコピーしない。
- VMでファイアウォールを使っている場合はWindowsホストのIPから8883/TCPのみ許可する。

設定項目は[Mosquitto公式設定資料](https://mosquitto.org/man/mosquitto-conf-5.html)を参照。
現在のアプリは遠隔Brokerの平文接続を許可しない。まずSSHトンネルで動作確認し、その後必要に応じてTLS listenerを整備する。

## VMwareで接続できない場合

VMwareの仮想NICが「接続済み」であることを確認する。NATでは通常ホストからVMへ接続でき、ホストオンリーではホスト・VM間、ブリッジでは同じLANから接続する構成になる。
実際の到達性はWindowsの仮想アダプター・ルーティング・ファイアウォールでも変わるため、`Test-NetConnection`のTCP結果で判断する。
ネットワーク方式の説明は[Broadcom公式資料](https://knowledge.broadcom.com/external/article?legacyId=1006480)を参照する。

| 症状 | 確認すること |
|---|---|
| SSHの22番へ接続できない | VMのIP変更、SSHサービス、VMware NIC、Windows/Ubuntuのファイアウォール |
| SSHが「Address already in use」 | Windowsの転送元ポートが使用中。18885などへ変更 |
| トンネル接続時に拒否される | VMの127.0.0.1:18884でBrokerが待ち受けているか |
| アプリの接続が繰り返し切れる | 同じ機器IDのアプリを別のPCやプロセスでも動かしていないか |
| MQTTは届くがDB件数が増えない | Python受信器の起動、購読先Broker、台帳の機器ID、DB接続、拒否ログ |
| TLS接続に失敗する | CA、証明書の期限、SANのIP、ポート、Broker側証明書・認証 |

模擬設備の「送信元IP」にVMのIPを入力しない。Windows上で動くアプリの送信元IPはWindows自身のアドレス。
12台の模擬設備は同じWindows IPから同じBrokerへ接続して問題ない。
