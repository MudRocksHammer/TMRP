# TMRP Device Simulator

電力設備を模擬するWindows／Linux向けデスクトップアプリ。
MQTTで電力データを送信し、受信した開閉指令に応答する。

## 機能

- 最大64台の設備を追加・編集・削除し、設定をJSONに保存する。
- 設備ごとにBrokerのIP・ポート、送信元IP、認証、TLS、送信頻度を設定する。
- 個別または一括で接続・周期送信・停止する。送信頻度は0.1〜50Hz。
- 電圧・電流・力率・周波数、欠損値、遠方操作許可、インターロックを設定する。
- 遮断器を模擬開閉し、受信指令と受付・完了・拒否結果を表示する。
- 設備状態・指令結果をSQLiteへ保存し、同じ指令の重複実行を防ぐ。

## 使用技術

| 用途 | 技術 |
|---|---|
| アプリ・画面 | C++17、Qt 6 Widgets |
| 通信 | libmosquitto、MQTT 3.1.1／QoS 1、TLS |
| 保存 | SQLite、JSON |
| ビルド・テスト | CMake、vcpkg、QtTest |

## 起動手順

サーバーとBrokerは[プロジェクトのREADME](../README.md#起動手順)に従って起動する。
以下のコマンドはTMRPルートで実行する。

### Windows

Windows x64、PowerShell、wingetを使用する。Visual Studio 2022／2026が導入済みの場合は、
Visual Studio Installerで「C++によるデスクトップ開発」（MSVC、Windows SDK、CMakeツール）を追加する。

```powershell
# Windows側のプロジェクトへ移動する（実際の保存先に変更する）
cd C:\dev\TMRP

# Qt・vcpkg・不足する開発ツールを準備し、ビルド・テスト後に起動する
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\setup-windows.ps1 -Launch
```

初回はネット接続と、インストーラーの管理者権限確認が必要。
既定のQtは6.8.3 MSVC x64。VS 2026ではCMake 4.2以降を使用する。
ツールは`%LOCALAPPDATA%\TMRP\toolchains`、パス設定は`.deps/windows-toolchain.json`へ保存する。

```powershell
# 既存のQtとvcpkgを指定する場合
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\setup-windows.ps1 `
  -QtPrefix C:\Qt\6.8.3\msvc2022_64 -VcpkgRoot C:\dev\vcpkg -Launch

# 次回以降、保存した設定で再ビルドする
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\build-windows.ps1

# VS 2026でビルドしたアプリを起動する
& .\device-simulator\build-windows-vs2026\Release\tmrp-device-simulator.exe
```

VS 2022の出力先は`build-windows\Release\tmrp-device-simulator.exe`。
配布時はexeだけでなく、出力先のDLL・プラグインも含める。

### Linux（Ubuntu 24.04）

```bash
# C++・Qt・MQTTの開発パッケージと日本語フォントを導入する
sudo apt update
sudo apt install build-essential cmake qt6-base-dev libqt6sql6-sqlite libmosquitto-dev fonts-noto-cjk

# ビルドしてアプリを起動する
bash device-simulator/scripts/run.sh
```

### WindowsからUbuntu VMへ接続する

VMが`192.168.237.128`、SSHユーザーが`shou`の場合。VM内のBrokerは18884番で起動しておく。
Windowsの別のPowerShellで実行し、接続中は端末を開いたままにする。

```powershell
# Windowsの18884番をSSH経由でVMのBrokerへ転送する
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
  -L 127.0.0.1:18884:127.0.0.1:18884 shou@192.168.237.128
```

アプリで「設備を追加」を押し、次の値を設定する。

| 項目 | 値 |
|---|---|
| 機器ID | `power-meter-001`〜`power-meter-012`。設備ごとに別ID |
| 設備ID | 対応する`breaker-001`〜`breaker-012` |
| Broker IP／ポート | `127.0.0.1`／`18884` |
| 送信元IP | 空欄 |
| TLS | オフ（SSHトンネルを使用） |
| 送信頻度 | 1 Hz |

「接続」→「定期送信を開始」で送信する。Linuxで同じPCのBrokerへ接続する場合も、この設定を使う。
送信元IPを指定する場合は、アプリを動かすPCに割り当て済みのIPを使う。
新しい機器IDはサーバーの`examples/power/assets.json`にも登録し、受信サーバーを再起動する。

### 操作指令を送る

アプリを接続した状態で、Ubuntu側のTMRPルートから実行する。

```bash
# 設備001へ開指令を送り、操作結果を表示する
.venv/bin/python device-simulator/scripts/send_command.py --operation open_breaker

# 設備001へ閉指令を送る
.venv/bin/python device-simulator/scripts/send_command.py --operation close_breaker
```

対象設備の画面で遮断器状態と「受信指令・操作結果」を確認する。
